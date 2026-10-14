"""Synthetic batch-seam coverage; never reads a real seal or production data."""
from __future__ import annotations

import copy
import base64
import hashlib
import io
import json
import math
import os
import unittest
from pathlib import Path
from unittest import mock

import fitz
from PIL import Image
from reportlab.pdfgen import canvas

import backend
from editor_seam import (
    require_grouped_company_seal,
    seam_element_for_position,
    split_seal_raster,
    validate_seam_groups,
    validate_seam_positions,
)
from tests import test_five_account_editor_workflow as workflow_fixture
from tests import test_general_document_seal_workflow as general_seal_fixture


def grouped_fixture(page_count=7, edge="right", rotations=(0, 90, 180, 270), *, size=84, height_size=None, offset=120):
    seal_width,seal_height=size,size if height_size is None else height_size
    pages = [{"pageId": f"p{i}", "order": i + 1, "widthPt": 595.2756, "heightPt": 841.8898,
              "rotation": rotations[i % len(rotations)]} for i in range(page_count)]
    elements = []
    for start in range(0, page_count, 5):
        count = min(5, page_count - start)
        for index in range(count):
            page = pages[start + index]
            width, height, rotation = page["widthPt"], page["heightPt"], page["rotation"]
            display_width, display_height = (height, width) if rotation % 180 else (width, height)
            displayed_seal_width,displayed_seal_height=(seal_height,seal_width) if rotation % 180 else (seal_width,seal_height)
            group_offset = offset + start * 12
            left = 0 if edge == "left" else display_width - displayed_seal_width if edge == "right" else group_offset
            top = 0 if edge == "top" else display_height - displayed_seal_height if edge == "bottom" else group_offset
            if rotation == 90: x, y = top, left
            elif rotation == 180: x, y = width - left - seal_width, top
            elif rotation == 270: x, y = width - top - seal_width, height - left - seal_height
            else: x, y = left, height - top - seal_height
            elements.append({"id": f"s{start}-{index}", "pageId": page["pageId"], "kind": "seal",
                "x": round(x,4), "y": round(y,4), "width": seal_width, "height": seal_height, "rotation": 0,
                "opacity": 1, "zIndex": len(elements) + 1,
                "properties": {"sealId": "synthetic-company-seal", "sealFileId": "synthetic-file",
                    "sealFileSha256": "a" * 64, "seamGroupId": f"group-{start // 5}",
                    "seamMode": "grouped", "seamPartCount": count, "seamPartIndex": index, "seamEdge": edge}})
    return {"pages": pages, "elements": elements}


def locked_position(element):
    props = element["properties"]
    return {**{key: element[key] for key in ("x", "y", "width", "height", "rotation", "opacity")},
        "page_ref": element["pageId"], "order_index": element["zIndex"], "z_index": element["zIndex"],
        "locked_seal_file_id": props["sealFileId"], "locked_seal_sha256": props["sealFileSha256"]}


class GroupedSeamGeometryTests(unittest.TestCase):
    def test_exact_group_sizes_edges_and_page_rotations(self):
        for count, expected in ((7,[5,2]), (8,[5,3]), (10,[5,5]), (6,[5,1]), (1,[1])):
            for edge in ("left", "right", "top", "bottom"):
                with self.subTest(pages=count, edge=edge):
                    state = grouped_fixture(count, edge)
                    self.assertEqual([len(members) for members in validate_seam_groups(state).values()], expected)
                    positions = [locked_position(item) for item in state["elements"]]
                    validate_seam_positions(state, positions)
                    for item, position in zip(state["elements"], positions):
                        self.assertEqual(seam_element_for_position(state, position), item)
                        self.assertEqual((item["width"], item["height"]), (84,84))

    def test_missing_duplicate_out_of_range_or_inconsistent_members_rejected(self):
        mutations = (
            lambda state: state["elements"].pop(2),
            lambda state: state["elements"][2]["properties"].update(seamPartIndex=1),
            lambda state: state["elements"][2]["properties"].update(seamPartIndex=True),
            lambda state: state["elements"][2]["properties"].update(seamPartIndex=5),
            lambda state: state["elements"][2]["properties"].update(seamPartCount=True),
            lambda state: state["elements"][2]["properties"].update(seamPartCount=6),
            lambda state: state["elements"][2]["properties"].update(seamPartCount=0),
            lambda state: state["elements"][2]["properties"].update(seamEdge="diagonal"),
            lambda state: state["elements"][2]["properties"].update(seamEdge=[]),
            lambda state: state["elements"][2]["properties"].pop("seamEdge"),
            lambda state: state["elements"][2]["properties"].update(seamEdge="left"),
            lambda state: state["elements"][2]["properties"].update(seamMode="pair"),
            lambda state: state["elements"][2]["properties"].update(sealFileId="foreign-file"),
            lambda state: state["elements"][2]["properties"].update(sealFileSha256="b" * 64),
            lambda state: state["elements"][2].update(pageId="p1"),
            lambda state: state["elements"][2].update(width=20),
            lambda state: state["elements"][2].update(opacity=.4),
            lambda state: state["elements"][2].update(rotation=90),
            lambda state: state["elements"][2].update(x=15),
            lambda state: state["elements"][2].update(y=15),
            lambda state: state["pages"].reverse(),
        )
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=index):
                state = grouped_fixture(rotations=(0,))
                mutation(state)
                with self.assertRaises(ValueError): validate_seam_groups(state)

    def test_orphan_metadata_and_partial_locked_output_rejected(self):
        state = grouped_fixture()
        state["elements"][0]["properties"].pop("seamGroupId")
        with self.assertRaisesRegex(ValueError,"editor_seam_group_invalid"): validate_seam_groups(state)
        state = grouped_fixture()
        positions = [locked_position(item) for item in state["elements"]]
        for forged in (positions[:5], positions[:-1], [], positions + [positions[0]], [positions[0]] * 7):
            with self.assertRaisesRegex(ValueError,"editor_seam_position_mismatch"):
                validate_seam_positions(state, forged)
        for field, value in (("page_ref","other-page"), ("locked_seal_sha256","b" * 64), ("locked_seal_file_id","foreign-file"), ("width",20), ("order_index",0), ("order_index",True), ("order_index","1")):
            position = copy.deepcopy(positions[0]); position[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,"editor_seam_position_mismatch"):
                seam_element_for_position(state,position)

    def test_only_classified_owners_own_primary_large_seal_allowed_for_new_groups(self):
        element = grouped_fixture()["elements"][0]
        valid = {"owner_kind":"company", "seal_category":"establishment_seal", "seal_size_type":"large_seal"}
        require_grouped_company_seal(element,valid)
        institution={"owner_kind":"institution","seal_category":"official_seal","seal_size_type":"large_seal"}
        require_grouped_company_seal(element,institution)
        for patch in ({"owner_kind":"institution"}, {"owner_kind":"unclassified"}, {"seal_category":"general_seal"},
                      {"seal_category":"official_seal"}, {"seal_category":"continuous_seal"}, {"seal_size_type":"small_seal"}):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError,"editor_seam_company_large_seal_required"):
                require_grouped_company_seal(element,{**valid, **patch})
        for patch in ({"owner_kind":"company"},{"owner_kind":"unclassified"},{"owner_kind":None},{"owner_kind":[]},
                      {"seal_category":"establishment_seal"},{"seal_category":"general_seal"},{"seal_category":"bank_seal"},
                      {"seal_category":"continuous_seal"},{"seal_size_type":"small_seal"},{"seal_size_type":"single_seal"}):
            with self.subTest(institution_patch=patch),self.assertRaisesRegex(ValueError,"editor_seam_company_large_seal_required"):
                require_grouped_company_seal(element,{**institution,**patch})
        legacy = copy.deepcopy(element); legacy["properties"]["seamMode"] = "pair"
        require_grouped_company_seal(legacy,{"owner_kind":"unclassified","seal_category":"general_seal"})

    def test_both_backend_adapters_reject_wrong_category_before_resolving_file(self):
        element = grouped_fixture()["elements"][0]
        wrong = {"owner_kind":"company","seal_category":"general_seal","seal_size_type":"large_seal"}
        with mock.patch.object(backend,"validate_official_document_seal",return_value=wrong), \
             mock.patch.object(backend,"supabase_validate_official_document_seal",return_value=wrong), \
             mock.patch.object(backend,"supabase_filter_rows") as storage:
            with self.assertRaisesRegex(ValueError,"editor_seam_company_large_seal_required"):
                backend.local_editor_seal_file_context(None,"CO-SYNTHETIC",element,bind_missing=False,require_current_selection=True)
            with self.assertRaisesRegex(ValueError,"editor_seam_company_large_seal_required"):
                backend.supabase_editor_seal_file_context("CO-SYNTHETIC",element,bind_missing=False,require_current_selection=True)
            storage.assert_not_called()

    def test_element_owner_claim_cannot_override_attested_backend_owner(self):
        element=grouped_fixture()["elements"][0]
        element["properties"].update(owner_kind="institution",seal_category="official_seal",seal_size_type="large_seal")
        wrong={"owner_kind":"company","seal_category":"official_seal","seal_size_type":"large_seal"}
        with mock.patch.object(backend,"validate_official_document_seal",return_value=wrong), \
             mock.patch.object(backend,"supabase_validate_official_document_seal",return_value=wrong), \
             mock.patch.object(backend,"supabase_filter_rows") as storage:
            for adapter,args in ((backend.local_editor_seal_file_context,(None,"CO-SYNTHETIC",element)),
                                 (backend.supabase_editor_seal_file_context,("CO-SYNTHETIC",element))):
                with self.assertRaisesRegex(ValueError,"editor_seam_company_large_seal_required"):
                    adapter(*args,bind_missing=False,require_current_selection=True)
            storage.assert_not_called()


class GroupedSeamRasterTests(unittest.TestCase):
    def test_every_pixel_reconstructs_original_without_resampling_for_all_group_sizes(self):
        image = Image.new("RGBA",(103,107))
        for y in range(image.height):
            for x in range(image.width): image.putpixel((x,y),(x,y,100,255))
        stream = io.BytesIO(); image.save(stream,"PNG"); original = stream.getvalue()
        digest = hashlib.sha256(original).hexdigest()
        for count in range(1,6):
            for edge in ("left","right","top","bottom"):
                for rotation in (0,90,180,270):
                    with self.subTest(count=count,edge=edge,rotation=rotation):
                        horizontal = edge in {"top","bottom"}
                        displayed=image.rotate(-rotation,expand=True)
                        extent = displayed.height if horizontal else displayed.width
                        reconstructed = Image.new("RGBA",displayed.size)
                        for index in range(count):
                            rendered = Image.open(io.BytesIO(split_seal_raster(original,index,rotation,part_count=count,edge=edge)))
                            self.assertEqual(rendered.size,image.size)
                            rendered = rendered.rotate(-rotation,expand=True)
                            start,end = extent*index//count,extent*(index+1)//count
                            target = extent-(end-start) if edge in {"right","bottom"} else 0
                            strip = rendered.crop((0,target,displayed.width,target+end-start) if horizontal else (target,0,target+end-start,displayed.height))
                            reconstructed.paste(strip,(0,start) if horizontal else (start,0))
                            bbox = rendered.getbbox()
                            self.assertEqual(bbox, (0,target,displayed.width,target+end-start) if horizontal else (target,0,target+end-start,displayed.height))
                        self.assertEqual(reconstructed.tobytes(),displayed.tobytes())
        self.assertEqual(hashlib.sha256(original).hexdigest(),digest)

    def test_invalid_crop_arguments_fail_closed(self):
        stream=io.BytesIO(); Image.new("RGBA",(10,10),"red").save(stream,"PNG")
        for index,count,edge in ((True,5,"right"),(0,True,"right"),(5,5,"right"),(0,6,"right"),(0,0,"right"),(0,5,"pair"),(0,5,"invalid"),(0,5,[])):
            with self.subTest(index=index,count=count,edge=edge), self.assertRaisesRegex(ValueError,"editor_seam_group_invalid"):
                split_seal_raster(stream.getvalue(),index,part_count=count,edge=edge)

    def test_watermarked_original_scan_preview_preserves_aspect_without_mutating_binding_hash(self):
        for width,height in ((235,237),(235,470),(35,250)):
            source=io.BytesIO(); Image.new("RGBA",(width,height),(180,0,0,255)).save(source,"PNG",dpi=(200,200))
            original=source.getvalue(); digest=hashlib.sha256(original).hexdigest()
            preview=backend.generate_editor_seal_preview(original,"image/png",preserve_canvas_aspect=True)
            with Image.open(io.BytesIO(preview)) as image:
                self.assertLessEqual(max(image.size),320)
                self.assertAlmostEqual(image.width/image.height,width/height,delta=.005)
            self.assertEqual(hashlib.sha256(original).hexdigest(),digest)
            self.assertNotEqual(hashlib.sha256(preview).hexdigest(),digest)
        square=io.BytesIO(); Image.new("RGBA",(235,235),(180,0,0,255)).save(square,"PNG",dpi=(200,200))
        # Square pair/ordinary previews retain the exact historical derivative.
        self.assertEqual(backend.generate_editor_seal_preview(square.getvalue(),"image/png"),
                         backend.generate_editor_seal_preview(square.getvalue(),"image/png",preserve_canvas_aspect=True))


def assert_rendered_strips(testcase, pdf_bytes, state):
    """Measure colored output at 144 DPI, including PDF /Rotate semantics."""
    with fitz.open(stream=pdf_bytes,filetype="pdf") as document:
        testcase.assertEqual(len(document),len(state["pages"]))
        for page_index,page in enumerate(document):
            element = next(item for item in state["elements"] if item["pageId"] == state["pages"][page_index]["pageId"])
            edge, count = element["properties"]["seamEdge"], element["properties"]["seamPartCount"]
            displayed = fitz.Rect(element["x"],page.mediabox.height-element["y"]-element["height"],
                element["x"]+element["width"],page.mediabox.height-element["y"]) * page.rotation_matrix
            pix = page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            image = Image.frombytes("RGB",(pix.width,pix.height),pix.samples)
            colored = []
            # Restrict scan to the seal box; synthetic body text is not evidence.
            left,top,right,bottom = (round(value*2) for value in (displayed.x0,displayed.y0,displayed.x1,displayed.y1))
            for y in range(max(0,top-1),min(image.height,bottom+2)):
                for x in range(max(0,left-1),min(image.width,right+2)):
                    r,g,b = image.getpixel((x,y))
                    if r > g+60 and r > b+60: colored.append((x,y))
            testcase.assertTrue(colored,f"Missing strip page {page_index+1} edge {edge}")
            box=(min(x for x,y in colored),min(y for x,y in colored),max(x for x,y in colored)+1,max(y for x,y in colored)+1)
            horizontal=edge in {"top","bottom"}
            testcase.assertAlmostEqual((box[3]-box[1]) if horizontal else (box[2]-box[0]),
                displayed.height*2/count if horizontal else displayed.width*2/count,delta=2)
            testcase.assertAlmostEqual((box[2]-box[0]) if horizontal else (box[3]-box[1]),
                displayed.width*2 if horizontal else displayed.height*2,delta=2)
            if edge=="left": testcase.assertLessEqual(box[0],1)
            elif edge=="right": testcase.assertGreaterEqual(box[2],pix.width-2)
            elif edge=="top": testcase.assertLessEqual(box[1],1)
            else: testcase.assertGreaterEqual(box[3],pix.height-2)


class GroupedSeamPdfRendererTests(unittest.TestCase):
    def test_final_renderer_exact_strips_for_page_counts_edges_and_rotations(self):
        stream=io.BytesIO(); Image.new("RGBA",(400,400),(180,0,0,255)).save(stream,"PNG")
        seal=stream.getvalue(); seal_hash=hashlib.sha256(seal).hexdigest()
        for count in (7,8,10,6,1):
            for edge in ("left","right","top","bottom"):
                for rotation in (0,90,180,270):
                    with self.subTest(pages=count,edge=edge,rotation=rotation):
                        state=grouped_fixture(count,edge,rotations=(rotation,))
                        document=fitz.open()
                        for definition in state["pages"]:
                            page=document.new_page(width=definition["widthPt"],height=definition["heightPt"])
                            page.set_rotation(definition["rotation"])
                        prepared=document.tobytes(); document.close()
                        locked={"state":state,"prepared_bytes":prepared,"positions":[locked_position(item) for item in state["elements"]],
                            "seal_assets":{"synthetic-file":{"data":seal,"mime_type":"image/png"}},"renderer_version":"synthetic"}
                        result,_,metadata=backend.stamp_prepared_pdf_with_locked_seals(locked)
                        self.assertEqual(metadata["seal_count"],count)
                        self.assertEqual(metadata["seam_group_count"],(count+4)//5)
                        assert_rendered_strips(self,result,state)
        self.assertEqual(hashlib.sha256(seal).hexdigest(),seal_hash)

    def test_rectangular_native_pixels_and_physical_dimensions_do_not_pad_or_squeeze(self):
        for pixel_width,pixel_height in ((235,237),(235,470)):
            width_pt,height_pt=pixel_width/200*72,pixel_height/200*72
            stream=io.BytesIO(); Image.new("RGBA",(pixel_width,pixel_height),(180,0,0,255)).save(stream,"PNG")
            original=stream.getvalue()
            for edge in ("left","right","top","bottom"):
                for rotation in (0,90,180,270):
                    with self.subTest(pixels=(pixel_width,pixel_height),edge=edge,rotation=rotation):
                        state=grouped_fixture(7,edge,rotations=(rotation,),size=width_pt,height_size=height_pt)
                        document=fitz.open()
                        for definition in state["pages"]:
                            page=document.new_page(width=definition["widthPt"],height=definition["heightPt"])
                            page.set_rotation(definition["rotation"])
                        prepared=document.tobytes(); document.close()
                        locked={"state":state,"prepared_bytes":prepared,"positions":[locked_position(item) for item in state["elements"]],
                            "seal_assets":{"synthetic-file":{"data":original,"mime_type":"image/png"}},"renderer_version":"synthetic"}
                        result,_,_=backend.stamp_prepared_pdf_with_locked_seals(locked)
                        assert_rendered_strips(self,result,state)
                        with fitz.open(stream=result,filetype="pdf") as output:
                            for page in output:
                                inserted=page.get_image_info()[0]
                                self.assertEqual((inserted["width"],inserted["height"]),(pixel_width,pixel_height))
                                bbox=fitz.Rect(inserted["bbox"])
                                self.assertAlmostEqual(bbox.width,width_pt,delta=.001)
                                self.assertAlmostEqual(bbox.height,height_pt,delta=.001)

    def test_ordinary_approved_original_uses_native_pixels_opacity_and_pdf_affine_rotation(self):
        for pixel_width,pixel_height in ((235,237),(235,470)):
            width_pt,height_pt=pixel_width/200*72,pixel_height/200*72
            image=Image.new("RGBA",(pixel_width,pixel_height),(180,0,0,255))
            image.paste((0,0,180,255),(0,0,pixel_width,10))
            stream=io.BytesIO(); image.save(stream,"PNG"); original=stream.getvalue()
            digest=hashlib.sha256(original).hexdigest()
            for page_rotation in (0,90,180,270):
                for seal_rotation in (0,90,180,270,35):
                    for opacity in (1,.5):
                        with self.subTest(pixels=image.size,page_rotation=page_rotation,seal_rotation=seal_rotation,opacity=opacity):
                            definition={"pageId":"native-page","order":1,"widthPt":595.2756,"heightPt":841.8898,"rotation":page_rotation}
                            element={"id":"native-seal","kind":"seal","pageId":"native-page","x":200,"y":300,
                                "width":width_pt,"height":height_pt,"rotation":seal_rotation,"opacity":opacity,"zIndex":1,
                                "properties":{"sealFileId":"synthetic-file","sealFileSha256":"a"*64}}
                            state={"pages":[definition],"elements":[element]}
                            document=fitz.open(); page=document.new_page(width=definition["widthPt"],height=definition["heightPt"])
                            page.set_rotation(page_rotation); prepared=document.tobytes(); document.close()
                            position=locked_position(element); position["locked_dimension_policy_version"]=backend.seal_scan_exceptions.POLICY
                            locked={"state":state,"prepared_bytes":prepared,"positions":[position],
                                "seal_assets":{"synthetic-file":{"data":original,"mime_type":"image/png"}},"renderer_version":"synthetic"}
                            result,_,metadata=backend.stamp_prepared_pdf_with_locked_seals(locked)
                            self.assertEqual(metadata["seal_count"],1)
                            with fitz.open(stream=result,filetype="pdf") as output:
                                self.assertEqual(output[0].rotation,page_rotation)
                                info=output[0].get_image_info()[0]
                                self.assertEqual((info["width"],info["height"]),image.size)
                                a,b,c,d,_,_=info["transform"]
                                self.assertAlmostEqual(math.hypot(a,b),width_pt,delta=.001)
                                self.assertAlmostEqual(math.hypot(c,d),height_pt,delta=.001)
                                self.assertAlmostEqual(a*c+b*d,0,delta=.01)
                                raster=output[0].get_images(full=True)[0]
                                embedded=Image.open(io.BytesIO(output.extract_image(raster[0])["image"]))
                                self.assertEqual(embedded.convert("RGB").tobytes(),image.convert("RGB").tobytes())
                                if opacity<1:
                                    self.assertGreater(raster[1],0)
                                    alpha=Image.open(io.BytesIO(output.extract_image(raster[1])["image"]))
                                    self.assertEqual(alpha.size,image.size)
                                    self.assertTrue(126<=alpha.getpixel((10,20))<=129)
            self.assertEqual(hashlib.sha256(original).hexdigest(),digest)


class GroupedSeamApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fixture=workflow_fixture.FiveAccountEditorWorkflowTestCase()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.conn=self.fixture.conn
        self.seal_id=self.conn.execute("SELECT id FROM company_seals WHERE company_id='CO-001' AND seal_category='establishment_seal' AND seal_size_type='large_seal' ORDER BY id LIMIT 1").fetchone()[0]
        stream=io.BytesIO(); Image.new("RGBA",(400,400),(180,0,0,255)).save(stream,"PNG")
        self.seal_bytes=stream.getvalue()
        backend.upload_company_seal_file(self.conn,self.seal_id,{"file_name":"synthetic-company-primary.png","file_mime_type":"image/png",
            "content_base64":base64.b64encode(self.seal_bytes).decode("ascii"),"actor":"isolated-grouped-seam"})

    @staticmethod
    def source_pdf(page_count):
        stream=io.BytesIO(); document=canvas.Canvas(stream,pagesize=(backend.EDOC_A4_WIDTH_PT,backend.EDOC_A4_HEIGHT_PT))
        for index in range(page_count):
            document.drawString(100,700,f"Synthetic batch approval page {index+1}; no personal data")
            document.showPage()
        document.save(); return stream.getvalue()

    def test_seven_page_last_snapshot_cas_approval_stamp_download_all_four_edges(self):
        seal_file=backend.require_current_company_seal_file(self.conn,self.seal_id)
        seal=backend.company_seal_row(self.conn,self.seal_id)
        profile=backend.company_seal_file_dimension_profile(seal["seal_size_type"],seal_file,current=True)
        for index,edge in enumerate(("left","right","top","bottom")):
            with self.subTest(edge=edge):
                applicant=self.fixture._session_for_user_id(self.fixture.applicant_ids[index])
                source=self.source_pdf(7); source_hash=backend.sha256_bytes(source)
                draft=backend.create_official_editor_draft(self.conn,{"company_id":"CO-001","title":"Synthetic grouped seam acceptance",
                    "request_reason":"Seven page synthetic batch; company large seal","document_category":"服務委託合約",
                    "dispatch_method":"no_dispatch_required"},applicant)
                document_id=draft["document_id"]
                intent=backend.create_official_editor_upload_intent(self.conn,document_id,{"asset_kind":"source_pdf",
                    "file_name":"synthetic-seven-page-group.pdf","mime_type":"application/pdf","size_bytes":len(source),"sha256":source_hash},applicant)
                backend.store_official_editor_local_upload(self.conn,document_id,intent["upload_id"],source,applicant,"application/pdf")
                revision=backend.finalize_official_editor_upload(self.conn,document_id,intent["upload_id"],{"sha256":source_hash},applicant)["editor_revision"]
                state=copy.deepcopy(revision["state"])
                grouped=grouped_fixture(7,edge,rotations=(0,),size=profile["width_pt"],height_size=profile["height_pt"])
                page_map={old["pageId"]:new["pageId"] for old,new in zip(grouped["pages"],state["pages"])}
                state["elements"]=grouped["elements"]
                for item in state["elements"]:
                    item["pageId"]=page_map[item["pageId"]]
                    item["properties"].update(sealId=self.seal_id,sealFileId=seal_file["id"],sealFileSha256=seal_file["file_hash"],
                        renderWidthMm=profile["width_mm"],renderHeightMm=profile["height_mm"],dimensionPolicyVersion=profile["dimension_policy_version"])
                if edge == "right":
                    for item in state["elements"]:
                        item["properties"]["seamPolicyVersion"] = "right-edge-10mm-v2"
                else:
                    # Historical manifests remain readable/editable without
                    # rewriting an already persisted edge policy. New requests
                    # may no longer create these unversioned placements.
                    prior = backend._insert_editor_revision(self.conn,document_id,state,applicant["user"])
                    revision = backend._editor_revision_public(prior)
                payload={"revisionNo":revision["revisionNo"],"baseManifestSha256":revision["manifestSha256"],"state":state}
                saved=backend.save_official_editor_state(self.conn,document_id,payload,applicant)
                with self.assertRaisesRegex(ValueError,"editor_revision_conflict"):
                    backend.save_official_editor_state(self.conn,document_id,payload,applicant)
                partial=copy.deepcopy(saved["state"]); partial["elements"].pop(2)
                with self.assertRaisesRegex(ValueError,"editor_seam_group_incomplete"):
                    backend.save_official_editor_state(self.conn,document_id,{"revisionNo":saved["revisionNo"],"baseManifestSha256":saved["manifestSha256"],"state":partial},applicant)
                self.assertEqual(backend.get_official_editor_state(self.conn,document_id,applicant)["manifestSha256"],saved["manifestSha256"])
                preflight=backend.preflight_official_editor(self.conn,document_id,{"editorRevisionId":saved["id"],"manifestSha256":saved["manifestSha256"]},applicant)
                detail=backend.submit_official_document(self.conn,document_id,{"editorRevisionId":preflight["editorRevisionId"],"manifestSha256":preflight["manifestSha256"],
                    "preparedFileId":preflight["preparedFileId"],"preparedSha256":preflight["preparedSha256"],
                    "expected_content_revision":backend.official_document_row(self.conn,document_id)["content_revision"]},applicant)
                locked=copy.deepcopy(detail["stamp_request"])
                locked_state=json.loads(self.conn.execute("SELECT editor_state_json FROM official_document_editor_revisions WHERE id=?",(locked["locked_editor_revision_id"],)).fetchone()[0])
                self.assertEqual([len(group) for group in validate_seam_groups(locked_state).values()],[5,2])
                self.assertEqual(len(locked["stamp_positions"]),7)
                with self.assertRaisesRegex(ValueError,"editor_locked_after_submit"):
                    backend.save_official_editor_state(self.conn,document_id,{"revisionNo":preflight["revisionNo"],"baseManifestSha256":preflight["manifestSha256"],"state":state},applicant)
                detail=self.fixture._approve_and_stamp(detail)
                stamped_meta=next(item for item in detail["files"] if item["file_type"]=="stamped_pdf")
                _,_,stamped=backend.official_document_download_file(self.conn,document_id,stamped_meta["id"],applicant)
                self.assertEqual(backend.sha256_bytes(stamped),stamped_meta["file_hash"])
                assert_rendered_strips(self,stamped,locked_state)
                for key in ("locked_editor_revision_id","locked_source_sha256","prepared_file_id","prepared_sha256","editor_manifest_sha256"):
                    self.assertEqual(detail["stamp_request"][key],locked[key])
                original=next(item for item in detail["files"] if item["file_type"]=="original_pdf")
                self.assertEqual(backend.official_document_download_file(self.conn,document_id,original["id"],applicant)[2],source)
                self.assertEqual(backend.read_file_object_bytes(self.conn,seal_file["file_object_id"])[1],self.seal_bytes)
                for participant in {step["approver_user_id"] for step in detail["approval_steps"] if step.get("approver_user_id")}:
                    self.assertEqual(backend.official_document_download_file(self.conn,document_id,stamped_meta["id"],self.fixture._session_for_user_id(participant))[2],stamped)
                detail=backend.confirm_official_document(self.conn,document_id,{"comment":"Synthetic batch received"},applicant)
                self.assertEqual(detail["current_status"],"closed")
                destination=os.environ.get("EDOC_GROUPED_SEAM_EVIDENCE_DIR")
                if destination:
                    output=Path(destination); output.mkdir(parents=True,exist_ok=True)
                    (output / f"synthetic-seven-page-{edge}-approved.pdf").write_bytes(stamped)

    def test_rectangular_approved_scan_fixture_completes_same_immutable_approval_flow(self):
        # This isolated registry entry is synthetic, not an authorization for
        # any deployed hash or actual artwork. Production's fixed 22 entries
        # are independently tested by test_seal_scan_exceptions.
        stream=io.BytesIO(); Image.new("RGBA",(235,237),(180,0,0,255)).save(stream,"PNG")
        native=stream.getvalue()
        entry=(backend.sha256_bytes(native).lower(),"CO-001",self.seal_id,"establishment_seal","large_seal",235,237,29.845,30.099,0)
        with mock.patch.object(backend.seal_scan_exceptions,"_ROWS",(*backend.seal_scan_exceptions._ROWS,entry)):
            backend.upload_company_seal_file(self.conn,self.seal_id,{"file_name":"synthetic-native-original.png","file_mime_type":"image/png",
                "content_base64":base64.b64encode(native).decode("ascii"),"render_width_mm":29.845,"render_height_mm":30.099,
                "actor":"isolated-approved-original"})
            self.seal_bytes=native
            with mock.patch.dict(os.environ,{"EDOC_GROUPED_SEAM_EVIDENCE_DIR":""}):
                self.test_seven_page_last_snapshot_cas_approval_stamp_download_all_four_edges()

    def test_institution_own_rectangular_primary_large_completes_immutable_approval_flow(self):
        backend.patch_company_seal_policy(self.conn,"CO-001",{"owner_kind":"institution"})
        row=self.conn.execute("SELECT id FROM company_seals WHERE company_id='CO-001' AND seal_category='official_seal' AND seal_size_type='large_seal' AND is_active=1 ORDER BY id LIMIT 1").fetchone()
        self.seal_id=row[0] if row else backend.create_company_seal(self.conn,"CO-001",{"seal_name":"Synthetic institution primary large","seal_category":"official_seal","seal_size_type":"large_seal"})["id"]
        stream=io.BytesIO();Image.new("RGBA",(400,800),(180,0,0,255)).save(stream,"PNG")
        self.seal_bytes=stream.getvalue()
        backend.upload_company_seal_file(self.conn,self.seal_id,{"file_name":"synthetic-institution-primary.png","file_mime_type":"image/png",
            "content_base64":base64.b64encode(self.seal_bytes).decode("ascii"),"render_width_mm":20,"render_height_mm":40,
            "actor":"isolated-institution-grouped-seam"})
        seal=backend.company_seal_row(self.conn,self.seal_id)
        self.assertEqual((seal["owner_kind"],seal["seal_category"],seal["seal_size_type"]),("institution","official_seal","large_seal"))
        seal_file=backend.require_current_company_seal_file(self.conn,self.seal_id)
        element=grouped_fixture()["elements"][0]
        element["properties"].update(sealId=self.seal_id,sealFileId=seal_file["id"],sealFileSha256=seal_file["file_hash"],
            owner_kind="company",seal_category="bank_seal",renderWidthMm=999,renderHeightMm=999)
        with general_seal_fixture.GeneralDocumentSealWorkflowTest._supabase_adapter(self):
            for name,adapter,args in (("SQLite",backend.local_editor_seal_file_context,(self.conn,"CO-001")),
                                      ("Supabase local adapter",backend.supabase_editor_seal_file_context,("CO-001",))):
                with self.subTest(adapter=name):
                    attested,file,profile=adapter(*args,copy.deepcopy(element),bind_missing=False,require_current_selection=True)
                    self.assertEqual(attested["owner_kind"],"institution")
                    self.assertEqual(file["id"],seal_file["id"])
                    self.assertEqual((profile["width_mm"],profile["height_mm"]),(20,40))
                    self.assertEqual(profile["dimension_policy_version"],backend.seal_policy.OFFICIAL_POLICY)
                    bad=copy.deepcopy(element);bad["properties"]["sealFileSha256"]="f"*64
                    with self.assertRaisesRegex(ValueError,"editor_seal_file_hash_mismatch"):
                        adapter(*args,bad,bind_missing=False,require_current_selection=True)
                    bad=copy.deepcopy(element);bad["properties"]["sealFileId"]="foreign-file"
                    with self.assertRaisesRegex(ValueError,"editor_seal_file_not_found"):
                        adapter(*args,bad,bind_missing=False,require_current_selection=True)
            with self.assertRaisesRegex(ValueError,"official_document_seal_company_mismatch"):
                backend.supabase_editor_seal_file_context("CO-FOREIGN",copy.deepcopy(element),bind_missing=False,require_current_selection=True)
            with self.assertRaisesRegex(ValueError,"official_document_seal_company_mismatch"):
                backend.local_editor_seal_file_context(self.conn,"CO-FOREIGN",copy.deepcopy(element),bind_missing=False,require_current_selection=True)
        with mock.patch.dict(os.environ,{"EDOC_GROUPED_SEAM_EVIDENCE_DIR":""}):
            self.test_seven_page_last_snapshot_cas_approval_stamp_download_all_four_edges()

    def test_institution_approved_original_200dpi_keeps_rectangular_native_geometry(self):
        backend.patch_company_seal_policy(self.conn,"CO-001",{"owner_kind":"institution"})
        self.seal_id=backend.create_company_seal(self.conn,"CO-001",{"seal_name":"Synthetic institution approved scan","seal_category":"official_seal","seal_size_type":"large_seal"})["id"]
        stream=io.BytesIO();Image.new("RGBA",(235,470),(180,0,0,255)).save(stream,"PNG")
        native=stream.getvalue()
        entry=(backend.sha256_bytes(native).lower(),"CO-001",self.seal_id,"official_seal","large_seal",235,470,29.845,59.69,0)
        with mock.patch.object(backend.seal_scan_exceptions,"_ROWS",(*backend.seal_scan_exceptions._ROWS,entry)):
            backend.upload_company_seal_file(self.conn,self.seal_id,{"file_name":"synthetic-institution-native-original.png","file_mime_type":"image/png",
                "content_base64":base64.b64encode(native).decode("ascii"),"render_width_mm":29.845,"render_height_mm":59.69,
                "actor":"isolated-approved-original-institution"})
            self.seal_bytes=native
            with mock.patch.dict(os.environ,{"EDOC_GROUPED_SEAM_EVIDENCE_DIR":""}):
                self.test_seven_page_last_snapshot_cas_approval_stamp_download_all_four_edges()


if __name__ == "__main__": unittest.main()
