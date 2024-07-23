from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from config import db_config

db = SQLAlchemy()

def create_app():
    app = Flask(__name__)
    app.config.from_object(db_config)

    db.init_app(app)

    from app import routes
    app.register_blueprint(routes.bp)

    return app