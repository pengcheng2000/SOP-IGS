import pytest
import sqlalchemy as sa
from app.sample_migration import upgrade_sample_scope


def test_legacy_scope_migration_preserves_ids_and_photo_references():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE photo_groups (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, test_item_id VARCHAR(80) NOT NULL, key TEXT NOT NULL)"))
        connection.execute(sa.text("CREATE TABLE photos (id TEXT PRIMARY KEY, photo_group_id TEXT REFERENCES photo_groups(id), path TEXT)"))
        connection.execute(sa.text("INSERT INTO photo_groups VALUES ('g','p','visual_inspection','test_photos')"))
        connection.execute(sa.text("INSERT INTO photos VALUES ('photo','g','original/file.jpg')"))
        upgrade_sample_scope(connection)
        upgrade_sample_scope(connection)
        assert connection.execute(sa.text("SELECT id,scope,test_item_id FROM photo_groups")).one() == ('g','test_item','visual_inspection')
        assert connection.execute(sa.text("SELECT * FROM photos")).one() == ('photo','g','original/file.jpg')
        connection.execute(sa.text("INSERT INTO photo_groups VALUES ('s','p',NULL,'front','sample')"))
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("INSERT INTO photo_groups VALUES ('bad','p',NULL,'bad','test_item')"))
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("INSERT INTO photo_groups VALUES ('duplicate','p',NULL,'front','sample')"))
        assert not connection.execute(sa.text("PRAGMA foreign_key_check")).all()
