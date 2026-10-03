import pytest

from app import create_app, db as database


@pytest.fixture
def app(tmp_path):
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "DATA_DIR": tmp_path,
        "AI_API_KEY": "",
        "AUTO_CREATE_DB": True,
    })
    with app.app_context():
        database.create_all()
        yield app
        database.session.remove()
        database.drop_all()


@pytest.fixture
def db(app):
    return database


@pytest.fixture
def client(app):
    return app.test_client()
