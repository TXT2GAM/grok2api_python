import os
from logger import logger


class AuthTokenManager:
    def __init__(self):
        self.tokens = []
        self.current_index = 0
        self.last_round_index = -1
        
    def add_token(self, token_str):
        if isinstance(token_str, dict):
            token_str = token_str.get("token", "")
        
        if token_str and token_str not in self.tokens:
            self.tokens.append(token_str)
            self.current_index = 0
            self.last_round_index = -1
            logger.info(f"令牌添加成功: {token_str[:20]}...", "TokenManager")
            return True
        return False
        
    def set_token(self, token_str):
        if isinstance(token_str, dict):
            token_str = token_str.get("token", "")
            
        self.tokens = [token_str]
        self.current_index = 0
        self.last_round_index = -1
        logger.info(f"设置单个令牌: {token_str[:20]}...", "TokenManager")

    def delete_token(self, token):
        try:
            if isinstance(token, dict):
                token = token.get("token", "")
                
            if token in self.tokens:
                self.tokens.remove(token)
                # 重置轮询状态以避免索引越界
                self.current_index = 0
                self.last_round_index = -1
                logger.info(f"令牌已成功移除: {token[:20]}...", "TokenManager")
                return True
            return False
        except Exception as error:
            logger.error(f"令牌删除失败: {str(error)}", "TokenManager")
            return False
    
    def get_next_token_for_model(self, model_id):
        if not self.tokens:
            return None
            
        # 检查是否开始新的一轮轮询
        if self.current_index == 0 and self.last_round_index != -1:
            # 开始新一轮轮询，重置索引
            self.current_index = 0
        else:
            # 记录上一轮的最后索引
            if self.current_index == len(self.tokens) - 1:
                self.last_round_index = self.current_index
        
        # 按序号依次轮询
        token = self.tokens[self.current_index]
        
        # 移动到下一个索引
        self.current_index = (self.current_index + 1) % len(self.tokens)
        
        return token

    def remove_failed_token(self, token):
        if isinstance(token, dict):
            token = token.get("token", "")
            
        if token in self.tokens:
            self.tokens.remove(token)
            # 重置轮询状态以避免索引越界
            self.current_index = 0
            self.last_round_index = -1
            logger.info(f"已移除失效令牌: {token[:20]}...", "TokenManager")
            return True
        return False

    def get_all_tokens(self):
        return self.tokens.copy()
        
    def get_token_status_map(self):
        status_map = {}
        for i, token in enumerate(self.tokens):
            if "sso=" in token:
                sso = token.split("sso=")[1].split(";")[0]
            else:
                sso = f"token_{i}"
                
            status_map[sso] = {
                "isValid": True,
                "index": i
            }
        return status_map
    
    def load_from_env(self):
        sso_array = os.environ.get("SSO", "").split(',')
        if sso_array and sso_array[0]:
            for value in sso_array:
                if value.strip():
                    token_str = f"sso-rw={value.strip()};sso={value.strip()}"
                    self.add_token(token_str)
        
        logger.info(f"令牌加载完成，共加载: {len(self.get_all_tokens())}个令牌", "TokenManager")
    
    def is_empty(self):
        return len(self.tokens) == 0