import os
import time
import json
import secrets
from flask import Flask, request, Response, jsonify, render_template, redirect, session
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config_manager
from logger import logger
from token_manager import AuthTokenManager
from request_handler import RequestHandler

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app)
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(16)
app.json.sort_keys = False

token_manager = AuthTokenManager()
request_handler = RequestHandler(token_manager)


def initialization():
    token_manager.load_from_env()
    
    if config_manager.get("API.PROXY"):
        logger.info(f"代理已设置: {config_manager.get('API.PROXY')}", "Server")

    logger.info("初始化完成", "Server")


@app.route('/manager/login', methods=['GET', 'POST'])
def manager_login():
    return redirect('/manager')


@app.route('/manager')
def manager():
    return render_template('manager.html')


@app.route('/manager/api/get')
def get_manager_tokens():
    return jsonify(token_manager.get_token_status_map())


@app.route('/manager/api/add', methods=['POST'])
def add_manager_token():
    try:
        sso = request.json.get('sso')
        if not sso:
            return jsonify({"error": "SSO token is required"}), 400
        
        token_str = f"sso-rw={sso};sso={sso}"
        token_manager.add_token(token_str)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/manager/api/delete', methods=['POST'])
def delete_manager_token():
    try:
        sso = request.json.get('sso')
        if not sso:
            return jsonify({"error": "SSO token is required"}), 400
        
        token_str = f"sso-rw={sso};sso={sso}"
        token_manager.delete_token(token_str)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/get/tokens', methods=['GET'])
def get_tokens():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if auth_token != config_manager.get("API.API_KEY"):
        return jsonify({"error": 'Unauthorized'}), 401
    return jsonify(token_manager.get_token_status_map())


@app.route('/add/token', methods=['POST'])
def add_token():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if auth_token != config_manager.get("API.API_KEY"):
        return jsonify({"error": 'Unauthorized'}), 401

    try:
        sso = request.json.get('sso')
        token_str = f"sso-rw={sso};sso={sso}"
        token_manager.add_token(token_str)
        return jsonify(token_manager.get_token_status_map().get(sso, {})), 200
    except Exception as error:
        logger.error(str(error), "Server")
        return jsonify({"error": '添加sso令牌失败'}), 500


@app.route('/delete/token', methods=['POST'])
def delete_token():
    auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
    if auth_token != config_manager.get("API.API_KEY"):
        return jsonify({"error": 'Unauthorized'}), 401

    try:
        sso = request.json.get('sso')
        token_str = f"sso-rw={sso};sso={sso}"
        token_manager.delete_token(token_str)
        return jsonify({"message": '删除sso令牌成功'}), 200
    except Exception as error:
        logger.error(str(error), "Server")
        return jsonify({"error": '删除sso令牌失败'}), 500


@app.route('/v1/models', methods=['GET'])
def get_models():
    return jsonify({
        "object": "list",
        "data": [
            {
                "id": model,
                "object": "model", 
                "created": int(time.time()),
                "owned_by": "grok"
            }
            for model in config_manager.get_models().keys()
        ]
    })


@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    response_status_code = 500
    
    try:
        auth_token = request.headers.get('Authorization', '').replace('Bearer ', '')
        if auth_token:
            if auth_token != config_manager.get("API.API_KEY"):
                return jsonify({"error": 'Unauthorized'}), 401
        else:
            return jsonify({"error": 'API_KEY缺失'}), 401

        data = request.json
        model = data.get("model")
        stream = data.get("stream", False)
        
        try:
            request_handler.validate_request(data)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        try:
            response = request_handler.make_grok_request(data, model, stream)
            
            if stream:
                return response
            else:
                return jsonify(response)
                
        except ValueError as e:
            response_status_code = 400
            logger.error(str(e), "ChatAPI")
            return jsonify({
                "error": {
                    "message": str(e),
                    "type": "invalid_request_error"
                }
            }), response_status_code
            
    except Exception as error:
        logger.error(str(error), "ChatAPI")
        return jsonify({
            "error": {
                "message": str(error),
                "type": "server_error"
            }
        }), response_status_code


@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def catch_all(path):
    return 'api运行正常', 200


if __name__ == '__main__':
    initialization()
    
    app.run(
        host='0.0.0.0',
        port=config_manager.get("SERVER.PORT"),
        debug=False
    )