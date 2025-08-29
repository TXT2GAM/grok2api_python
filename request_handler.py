import json
from flask import stream_with_context, Response, jsonify
from curl_cffi import requests as curl_requests
from logger import logger
from config import config_manager
from token_manager import AuthTokenManager
from message_processor import MessageProcessor


class RequestHandler:
    def __init__(self, token_manager: AuthTokenManager):
        self.token_manager = token_manager
        
        self.default_headers = {
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Content-Type': 'text/plain;charset=UTF-8',
            'Connection': 'keep-alive',
            'Origin': 'https://grok.com',
            'Priority': 'u=1, i',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
            'Sec-Ch-Ua': '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"macOS"',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Baggage': 'sentry-public_key=b311e0f2690c81f25e2c4cf6d4f7ce1c',
            'x-statsig-id': 'ZTpUeXBlRXJyb3I6IENhbm5vdCByZWFkIHByb3BlcnRpZXMgb2YgdW5kZWZpbmVkIChyZWFkaW5nICdjaGlsZE5vZGVzJyk='
        }
    
    def get_proxy_options(self):
        proxy = config_manager.get("API.PROXY")
        proxy_options = {}

        if proxy:
            logger.info(f"使用代理: {proxy}", "Server")
            
            if proxy.startswith("socks5://"):
                proxy_options["proxy"] = proxy
                
                if '@' in proxy:
                    auth_part = proxy.split('@')[0].split('://')[1]
                    if ':' in auth_part:
                        username, password = auth_part.split(':')
                        proxy_options["proxy_auth"] = (username, password)
            else:
                proxy_options["proxies"] = {"https": proxy, "http": proxy}     
        return proxy_options

    def handle_non_stream_response(self, response, model):
        try:
            logger.info("开始处理非流式响应", "Server")
            
            # 直接返回原始响应内容
            return response.content.decode('utf-8')
            
        except Exception as error:
            logger.error(str(error), "Server")
            raise

    def handle_stream_response(self, response, model):
        def generate():
            logger.info("开始处理流式响应", "Server")
            
            # 直接透传流式响应
            try:
                for chunk in response.iter_lines():
                    if not chunk:
                        continue
                    # 直接返回原始行，不做任何处理
                    yield chunk.decode('utf-8') + '\n'
            except Exception as e:
                logger.error(f"处理流式响应时出错: {str(e)}", "Server")
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        
        return generate()

    def make_grok_request(self, data, model, stream=False):
        response_status_code = 500
        
        try:
            retry_count = 0
            
            while retry_count < config_manager.get("RETRY.MAX_ATTEMPTS", 2):
                retry_count += 1
                
                token = self.token_manager.get_next_token_for_model(model)
                if not token:
                    raise ValueError('无可用令牌')
                
                config_manager.set("API.SIGNATURE_COOKIE", token)
                logger.info(f"当前令牌: {token[:50]}...", "Server")
                
                try:
                    request_payload = MessageProcessor.prepare_chat_messages(data.get("messages", []), model)
                    
                    proxy_options = self.get_proxy_options()
                    response = curl_requests.post(
                        f"{config_manager.get('API.BASE_URL')}/rest/app-chat/conversations/new",
                        headers={
                            **self.default_headers, 
                            "Cookie": token
                        },
                        data=json.dumps(request_payload),
                        impersonate="chrome133a",
                        stream=True,
                        **proxy_options
                    )
                    
                    logger.info(f"请求状态码: {response.status_code}", "Server")
                    
                    if response.status_code == 200:
                        response_status_code = 200
                        logger.info("请求成功", "Server")
                        
                        if stream:
                            return Response(
                                stream_with_context(self.handle_stream_response(response, model)),
                                content_type='text/event-stream'
                            )
                        else:
                            content = self.handle_non_stream_response(response, model)
                            # 直接返回原始GroK响应，不进行格式化
                            if content.startswith('{') and content.endswith('}'):
                                # 如果是JSON格式，直接返回
                                return jsonify(json.loads(content))
                            else:
                                # 如果不是JSON，直接返回原始内容
                                return content
                            
                    elif response.status_code == 403:
                        response_status_code = 403
                        logger.error("IP暂时被封禁，请稍后重试或者更换IP", "Server")
                        raise ValueError('IP暂时被封无法破盾，请稍后重试或者更换ip')
                        
                    elif response.status_code == 429:
                        response_status_code = 429
                        
                        self.token_manager.remove_failed_token(token)
                        if self.token_manager.is_empty():
                            raise ValueError("所有令牌都已失效，请添加新的令牌")
                    else:
                        logger.error(f"令牌异常错误状态! status: {response.status_code}", "Server")
                        self.token_manager.remove_failed_token(token)
                        
                except Exception as e:
                    logger.error(f"请求处理异常: {str(e)}", "Server")
                    continue
            
            if response_status_code == 403:
                raise ValueError('IP暂时被封无法破盾，请稍后重试或者更换ip')
            elif response_status_code == 500:
                raise ValueError('所有令牌都已失效，请添加新的令牌')    
                
        except Exception as error:
            logger.error(str(error), "ChatAPI")
            raise
            
    def validate_request(self, request_data):
        model = request_data.get("model")
        if not model:
            raise ValueError("模型参数缺失")
            
        if not config_manager.is_valid_model(model):
            raise ValueError(f"不支持的模型: {model}")
            
        messages = request_data.get("messages")
        if not messages or not isinstance(messages, list):
            raise ValueError("消息参数缺失或格式错误")
            
        return True