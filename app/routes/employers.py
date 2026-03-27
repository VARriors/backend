from flask import Blueprint, jsonify, request
from app import db
from bson.objectid import ObjectId

employers_bp = Blueprint('employers', __name__)
jobs_collection = db['jobs']
employers_collection = db['employers']
applications_collection = db['applications']

@employers_bp.route('/jobs', methods=['GET', 'POST'])
def jobs():
    if request.method == 'GET':
        offer_list = list(jobs_collection.find({}))
        for offer in offer_list:
            offer['_id'] = str(offer['_id'])
        return jsonify(offer_list), 200
        
    if request.method == 'POST':
        new_offer = request.json
        if not new_offer or 'title' not in new_offer:
            return jsonify({"error": "Missing title in payload"}), 400
        
        result = jobs_collection.insert_one(new_offer)
        return jsonify({"message": "Job offer created", "id": str(result.inserted_id)}), 201

@employers_bp.route('/applications/<employer_id>', methods=['GET'])
def get_employer_applications(employer_id):
    apps = list(applications_collection.find({"employer_id": employer_id}))
    for a in apps:
        a['_id'] = str(a['_id'])
    return jsonify(apps), 200