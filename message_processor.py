import uuid
import time
import json
import re
from logger import logger
from config import config_manager


class MessageProcessor:
    @staticmethod
    def create_chat_response(message, model, is_stream=False):
        base_response = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "created": int(time.time()),
            "model": model
        }

        if is_stream:
            return {
                **base_response,
                "object": "chat.completion.chunk",
                "choices": [{
                    "index": 0,
                    "delta": {
                        "content": message
                    }
                }]
            }

        return {
            **base_response,
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message
                },
                "finish_reason": "stop"
            }],
            "usage": None
        }
    
    @staticmethod
    def process_message_content(content):
        if isinstance(content, str):
            return content
        return None

    @staticmethod
    def remove_think_tags(text):
        if not isinstance(text, str):
            return text
            
        text = re.sub(r'<think>[\s\S]*?<\/think>', '', text).strip()
        text = re.sub(r'!\[image]\(data:.*?base64,.*?\)', '[图片]', text)
        return text

    @staticmethod
    def process_content(content):
        if isinstance(content, list):
            text_content = ''
            for item in content:
                if item["type"] == 'image_url':
                    text_content += ("[图片]" if not text_content else '\n[图片]')
                elif item["type"] == 'text':
                    processed_text = MessageProcessor.remove_think_tags(item["text"])
                    text_content += (processed_text if not text_content else '\n' + processed_text)
            return text_content
        elif isinstance(content, dict) and content is not None:
            if content["type"] == 'image_url':
                return "[图片]"
            elif content["type"] == 'text':
                return MessageProcessor.remove_think_tags(content["text"])
        return MessageProcessor.remove_think_tags(MessageProcessor.process_message_content(content))

    @staticmethod
    def prepare_chat_messages(messages, model):
        processed_messages = []
        last_role = None
        last_content = ''
        
        for current in messages:
            role = 'assistant' if current["role"] == 'assistant' else 'user'
            text_content = MessageProcessor.process_content(current.get("content", ""))
            
            if text_content:
                if role == last_role and last_content:
                    last_content += '\n' + text_content
                    processed_messages[-1] = f"{role.upper()}: {last_content}"
                else:
                    processed_messages.append(f"{role.upper()}: {text_content}")
                    last_content = text_content
                    last_role = role
        
        conversation = '\n'.join(processed_messages)
        
        if not conversation.strip():
            raise ValueError('消息内容为空!')
        
        return {
            "temporary": config_manager.get("API.IS_TEMP_CONVERSATION", False),
            "modelName": model,
            "message": conversation,
            "fileAttachments": [],
            "imageAttachments": [],
            "disableSearch": True,
            "enableImageGeneration": False,
            "returnImageBytes": False,
            "returnRawGrokInXaiRequest": False,
            "enableImageStreaming": False,
            "imageGenerationCount": 0,
            "forceConcise": False,
            "toolOverrides": {
                "imageGen": False,
                "webSearch": False,
                "xSearch": False,
                "xMediaSearch": False,
                "trendsSearch": False,
                "xPostAnalyze": False
            },
            "enableSideBySide": True,
            "sendFinalMetadata": True,
            "customPersonality": "",
            "deepsearchPreset": "",
            "isReasoning": config_manager.is_reasoning_model(model),
            "disableTextFollowUps": True
        }
    
    @staticmethod
    def process_model_response(response, model):
        result = {"token": None}
        
        if model in ["grok-3", "grok-4"]:
            result["token"] = response.get("token")
        
        return result