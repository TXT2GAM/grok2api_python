import os
import time
import json
import secrets
from functools import wraps
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


def admin_required(f):
    """管理员鉴权装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 检查session中是否有有效的管理员身份验证
        if session.get('admin_authenticated'):
            return f(*args, **kwargs)

        # 检查请求头中的管理员密钥
        admin_key = request.headers.get('X-Admin-Key')
        if admin_key and admin_key == config_manager.get("ADMIN.ADMIN_KEY"):
            session['admin_authenticated'] = True
            return f(*args, **kwargs)

        # 如果是AJAX请求，返回JSON错误
        if request.headers.get('Content-Type') == 'application/json' or request.is_json:
            return jsonify({"error": "Unauthorized access", "redirect": "/manager/login"}), 401

        # 否则重定向到登录页面
        return redirect('/manager/login')
    return decorated_function


def initialization():
    token_manager.load_from_env()
    
    if config_manager.get("API.PROXY"):
        logger.info(f"代理已设置: {config_manager.get('API.PROXY')}", "Server")

    logger.info("初始化完成", "Server")


@app.route('/manager/login', methods=['GET', 'POST'])
def manager_login():
    if request.method == 'POST':
        admin_key = request.json.get('admin_key') if request.is_json else request.form.get('admin_key')

        if admin_key and admin_key == config_manager.get("ADMIN.ADMIN_KEY"):
            session['admin_authenticated'] = True
            if request.is_json:
                return jsonify({"success": True, "redirect": "/manager"})
            else:
                return redirect('/manager')
        else:
            if request.is_json:
                return jsonify({"error": "Invalid admin key"}), 401
            else:
                return render_template('login.html', error="Invalid admin key")

    # GET请求，如果已经认证则直接跳转到管理页面
    if session.get('admin_authenticated'):
        return redirect('/manager')

    return render_template('login.html')


@app.route('/manager/logout', methods=['POST'])
@admin_required
def manager_logout():
    session.pop('admin_authenticated', None)
    return jsonify({"success": True, "redirect": "/manager/login"})


@app.route('/manager')
@admin_required
def manager():
    return render_template('manager.html')


@app.route('/manager/api/get')
@admin_required
def get_manager_tokens():
    return jsonify(token_manager.get_token_status_map())


@app.route('/manager/api/add', methods=['POST'])
@admin_required
def add_manager_token():
    try:
        data = request.json
        
        # 支持批量添加
        if 'tokens' in data:
            # 批量添加模式
            tokens = data.get('tokens', [])
            if not tokens:
                return jsonify({"error": "Tokens list is required"}), 400
            
            result = token_manager.add_tokens_batch(tokens)
            return jsonify({
                "success": True,
                "added": result["success"],
                "duplicates": result["duplicates"], 
                "failed": result["failed"]
            })
        else:
            # 单个添加模式（兼容旧版本）
            sso = data.get('sso')
            if not sso:
                return jsonify({"error": "SSO token is required"}), 400
            
            # 如果输入的是完整的cookie字符串，直接使用
            if 'sso=' in sso and 'sso-rw=' in sso:
                token_str = sso
            else:
                # 如果只是cookie值，构造完整的cookie字符串
                token_str = f"sso-rw={sso};sso={sso}"
                
            token_manager.add_token(token_str)
            return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/manager/api/delete', methods=['POST'])
@admin_required
def delete_manager_token():
    try:
        sso = request.json.get('sso')
        if not sso:
            return jsonify({"error": "SSO token is required"}), 400

        # 直接删除传入的完整cookie字符串
        token_manager.delete_token(sso)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/manager/api/log-level', methods=['GET'])
@admin_required
def get_log_level():
    """获取当前日志级别"""
    try:
        current_level = config_manager.get_log_level()
        supported_levels = config_manager.get_supported_log_levels()
        return jsonify({
            "current_level": current_level,
            "supported_levels": supported_levels
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/manager/api/log-level', methods=['POST'])
@admin_required
def set_log_level():
    """设置日志级别"""
    try:
        data = request.json
        level = data.get('level')

        if not level:
            return jsonify({"error": "Log level is required"}), 400

        # 设置配置管理器中的日志级别
        if config_manager.set_log_level(level):
            # 动态设置logger的级别
            if logger.set_level(level):
                return jsonify({
                    "success": True,
                    "message": f"日志级别已设置为 {level}",
                    "level": level
                })
            else:
                return jsonify({"error": "Failed to update logger level"}), 500
        else:
            supported_levels = config_manager.get_supported_log_levels()
            return jsonify({
                "error": f"Invalid log level. Supported levels: {supported_levels}"
            }), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/manager/api/test', methods=['POST'])
@admin_required
def test_manager_token():
    try:
        cookie = request.json.get('cookie')
        if not cookie:
            return jsonify({"error": "Cookie is required"}), 400
        
        # 构造测试请求数据
        test_data = {
            "model": "grok-3",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False
        }
        
        # 临时设置token进行测试
        original_tokens = token_manager.get_all_tokens()
        token_manager.tokens = [cookie]  # 临时替换为测试cookie
        token_manager.current_index = 0
        token_manager.last_round_index = -1
        
        try:
            # 发送测试请求
            response = request_handler.make_grok_request(test_data, "grok-3", False)
            
            # 恢复原始tokens
            token_manager.tokens = original_tokens
            token_manager.current_index = 0 
            token_manager.last_round_index = -1
            
            if response and isinstance(response, dict) and 'choices' in response:
                return jsonify({"success": True, "message": "Cookie测试成功"})
            else:
                return jsonify({"success": False, "error": "响应格式异常"})
                
        except Exception as test_error:
            # 恢复原始tokens
            token_manager.tokens = original_tokens
            token_manager.current_index = 0
            token_manager.last_round_index = -1
            return jsonify({"success": False, "error": str(test_error)})
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


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