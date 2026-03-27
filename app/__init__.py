from flask import Flask
from pymongo import MongoClient
from flask_cors import CORS
from dotenv import load_dotenv
import os

from app.routes.candidates import candidates_bp
from app.routes.employers import employers_bp
from app.routes.matching import matching_bp

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/mpraca")
mongo_client = MongoClient(MONGO_URI)
db = mongo_client.get_database()

def create_app():
    app = Flask(__name__)
    CORS(app)

    app.register_blueprint(candidates_bp, url_prefix='/api/candidates')
    app.register_blueprint(employers_bp, url_prefix='/api/employers')
    app.register_blueprint(matching_bp, url_prefix='/api/matching')

    @app.route('/', methods=['GET'])
    def index():
        return {"message": "Mega duży ważny błąd: API działa, ale to tylko testowy endpoint!"}
    
    @app.route('/health', methods=['GET'])
    def health_check():
        return {"status": "ok", "message": "mMurząd pracy API is running!"}

    return app
