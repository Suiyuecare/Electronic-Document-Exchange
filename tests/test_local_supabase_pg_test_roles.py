"""Reproduce the PG16+ non-superuser role-creator SET boundary, locally only."""
import os
from pathlib import Path
import unittest
import uuid


@unittest.skipUnless(os.getenv("EDOC_COMPOSE_TEST_PG_PORT"), "isolated PostgreSQL role fixture gate not enabled")
class LocalSupabasePgTestRoleTests(unittest.TestCase):
    def test_setup_enables_set_without_superuser_bypassrls_or_inherit(self):
        import psycopg
        from psycopg import sql
        args = {"host": "127.0.0.1", "port": int(os.environ["EDOC_COMPOSE_TEST_PG_PORT"]), "dbname": "postgres", "autocommit": True}
        admin = psycopg.connect(**args, user=os.getenv("EDOC_TEST_PG_USER", "seniorlifepr"))
        if not admin.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]:
            admin.close()
            self.skipTest("local regression needs a superuser only to create/drop isolated surrogate roles")
        creator = "ci_creator_" + uuid.uuid4().hex[:12]
        target = "ci_backend_" + uuid.uuid4().hex[:12]
        connection = None
        try:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN CREATEROLE NOSUPERUSER NOBYPASSRLS NOINHERIT").format(sql.Identifier(creator)))
            connection = psycopg.connect(**args, user=creator)
            source = (Path(__file__).parent / "support/local_supabase_pg_test_roles.sql").read_text()
            # Substitute isolated role names only; execute the exact shipped
            # conditional creation + membership statements under a non-superuser.
            setup = source.replace("edoc_backend", target)
            connection.execute(setup.split("grant ", 1)[0])
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(target)))
            membership = "SELECT bool_or(m.admin_option),bool_or(m.inherit_option),bool_or(m.set_option) FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid JOIN pg_roles u ON u.oid=m.member WHERE r.rolname=%s AND u.rolname=%s"
            before = admin.execute(membership, (target, creator)).fetchone()
            self.assertEqual((True, False, False), before)
            connection.execute(setup)
            connection.execute(setup)  # Existing-role branch is idempotent.
            connection.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(target)))
            self.assertEqual(target, connection.execute("SELECT current_user").fetchone()[0])
            connection.execute("RESET ROLE")
            after = admin.execute(membership, (target, creator)).fetchone()
            self.assertEqual((True, False, True), after)
            self.assertEqual((False, False), admin.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=%s", (creator,)).fetchone())
        finally:
            if connection:
                connection.close()
            for role in (target, creator):
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))
            admin.close()
