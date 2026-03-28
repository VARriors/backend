import os

from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

from app.db import init_mongo

load_dotenv()

mongo_client, db = init_mongo()

from app.routes.candidates import candidates_bp
from app.routes.candidate_questionnaire import candidate_questionnaire_bp
from app.routes.employers import employers_bp
from app.routes.matching import matching_bp
from app.routes.candidate_api import candidate_api_bp
from app.routes.jobs_api import jobs_api_bp
from app.routes.ledger import ledger_bp


def create_app():
    app = Flask(__name__)

    cors_origins_env = os.getenv('CORS_ORIGINS', '')
    if cors_origins_env.strip():
        cors_origins = [origin.strip() for origin in cors_origins_env.split(',') if origin.strip()]
    else:
        cors_origins = [
            'http://localhost:5001',
            'http://127.0.0.1:5001',
            'http://localhost:8081',
            'http://127.0.0.1:8081',
            'http://localhost:19006',
            'http://127.0.0.1:19006',
            'http://localhost:3000',
            'http://127.0.0.1:3000',
            'http://localhost:5173',
            'http://127.0.0.1:5173',
        ]

    CORS(
        app,
        resources={r"/api/*": {"origins": cors_origins}},
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
        allow_headers=['Content-Type', 'Authorization', 'X-Candidate-Id'],
    )

    app.register_blueprint(candidates_bp, url_prefix='/api/candidates')
    app.register_blueprint(candidate_questionnaire_bp, url_prefix='/api/candidates')
    app.register_blueprint(employers_bp, url_prefix='/api/employers')
    app.register_blueprint(ledger_bp, url_prefix='/api/ledger')
    app.register_blueprint(matching_bp, url_prefix='/api/matching')
    app.register_blueprint(candidate_api_bp, url_prefix='/api/candidate')
    app.register_blueprint(jobs_api_bp, url_prefix='/api')

    @app.route('/', methods=['GET'])
    def index():
        return {"message": "Mega duży ważny błąd: API działa, ale to tylko testowy endpoint!"}

    @app.route('/health', methods=['GET'])
    def health_check():
        try:
            mongo_client.admin.command("ping")
            database_status = "ok"
        except Exception:
            database_status = "error"

        return {
            "status": "ok" if database_status == "ok" else "degraded",
            "message": "mMurząd pracy API is running!",
            "database": database_status,
        }

    return app
