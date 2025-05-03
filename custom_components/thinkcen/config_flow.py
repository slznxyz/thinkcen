"""MQTT同步配置流程。"""
import logging
import json
import base64
import voluptuous as vol
from typing import List

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_MQTT_URL,
    CONF_ENTITY_TYPES,
    CONF_ENTITIES,
    SUPPORTED_ENTITY_TYPES,
)

_LOGGER = logging.getLogger(__name__)


class MqttSyncFlowMixin:
    """MQTT同步配置流程的共享逻辑混合类。"""
    
    def __init__(self):
        """初始化混合类。"""
        self._entity_types = []
        self._mqtt_url = None
        self._mqtt_port = None
        self._web_url = None
        self._username = None
        self._password = None
    
    async def _async_handle_entity_types_step(self, user_input, current_types=None):
        """处理实体类型选择步骤的共享逻辑。"""
        errors = {}

        if user_input is not None:
            entity_types = user_input.get(CONF_ENTITY_TYPES, [])
            
            if not entity_types or len(entity_types) == 0:
                errors["entity_types"] = "no_entity_types_selected"
            else:
                self._entity_types = entity_types
                return await self.async_step_entities()

        return self.async_show_form(
            step_id=CONF_ENTITY_TYPES,
            data_schema=self._create_entity_types_schema(current_types),
            errors=errors,
        )
    
    async def _async_handle_entities_step(self, user_input, process_result_func, current_entities=None):
        """处理实体选择步骤的共享逻辑。"""
        errors = {}

        if user_input is not None:
            entities = user_input.get(CONF_ENTITIES, [])
            
            if not entities or len(entities) == 0:
                errors["entities"] = "no_entities_selected"
            else:
                # 使用回调函数处理结果
                return await process_result_func(entities)

        # 获取实体列表
        entities = await self._get_entities_for_types(self._entity_types)

        return self.async_show_form(
            step_id=CONF_ENTITIES,
            data_schema=vol.Schema({
                vol.Optional(CONF_ENTITIES, default=current_entities if current_entities else None): 
                    selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=entities,
                            multiple=True,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    ),
            }),
            errors=errors,
        )
    
    def _create_entity_types_schema(self, default_types=None):
        """创建实体类型选择的Schema。"""

        entity_type_options = [
            {"value": entity_type["value"], "label": entity_type["name"]}
            for entity_type in SUPPORTED_ENTITY_TYPES
        ]
        
        schema_key = vol.Optional(
            CONF_ENTITY_TYPES, 
            default=default_types if default_types else None
        )
        
        return vol.Schema({
            schema_key: selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=entity_type_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
        })
    
    async def _get_entities_for_types(self, entity_types: List[str]):
        """根据实体类型获取实体列表。"""
        entities = []

        # 获取所有实体并按域筛选
        all_states = self.hass.states.async_all()
        
        # 按域筛选实体 - 移除了去重逻辑
        for entity_type in entity_types:
            # 使用列表推导式筛选特定域的实体
            domain_states = [
                state for state in all_states 
                if state.entity_id.split('.')[0] == entity_type
            ]
            
            for state in domain_states:
                entity_id = state.entity_id
                friendly_name = state.attributes.get("friendly_name", entity_id)
                entity_item = {"value": entity_id, "label": f"{friendly_name} ({entity_id})"}
                entities.append(entity_item)

        # 如果没有找到任何实体，提供一个提示选项
        if not entities:
            entities = [{"value": "", "label": "未找到匹配的实体"}]
            
        return entities
    
    def _get_connection_data(self):
        """获取连接数据字典。"""
        return {
            "mqtt_url": self._mqtt_url,
            "mqtt_port": self._mqtt_port,
            "web_url": self._web_url,
            "username": self._username,
            "password": self._password,
            CONF_ENTITY_TYPES: self._entity_types,
        }
        
    def _generate_title(self):
        """根据配置生成一个有意义的集成条目标题。"""
        if self._mqtt_url:
            return f"ThinkCen-{self._mqtt_url}"
        else:
            return "ThinkCen"


class MqttSyncFlowHandler(config_entries.ConfigFlow, MqttSyncFlowMixin, domain=DOMAIN):
    """处理MQTT同步配置流程。"""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_PUSH

    def __init__(self):
        """初始化配置流程。"""
        super().__init__()
        MqttSyncFlowMixin.__init__(self)
        self._entities = []

    async def async_step_user(self, user_input=None):
        """处理用户步骤，进入MQTT URL配置。"""
        return await self.async_step_mqtt_url(user_input)

    async def async_step_mqtt_url(self, user_input=None):
        """处理MQTT URL配置步骤。"""
        errors = {}

        if user_input is not None:
            base64_str = user_input[CONF_MQTT_URL]
            
            try:
                # 尝试解码base64字符串
                decoded_bytes = base64.b64decode(base64_str)
                json_str = decoded_bytes.decode('utf-8')
                config_data = json.loads(json_str)
                
                # 从解码后的JSON获取MQTT连接信息
                self._mqtt_url = config_data.get("mqtt_url")
                self._mqtt_port = config_data.get("port")
                self._web_url = config_data.get("web_url")
                self._username = config_data.get("username")
                self._password = config_data.get("password")
                
                # 验证必要的字段是否存在
                if not self._mqtt_url or not self._mqtt_port or not self._web_url or not self._username or not self._password:
                    errors["mqtt_url"] = "invalid_mqtt_url"
                    _LOGGER.error("缺少必要的MQTT连接参数: mqtt_url=%s, port=%s", 
                                  self._mqtt_url, self._mqtt_port)
                else:
                    # 优化：避免调试级别的详细日志
                    if _LOGGER.isEnabledFor(logging.INFO):
                        _LOGGER.info("成功解析MQTT连接信息: %s:%s", self._mqtt_url, self._mqtt_port)
                    
                    return await self.async_step_entity_types()
            except Exception as e:
                _LOGGER.error("解析Token失败: %s", str(e))
                errors["mqtt_url"] = "invalid_user_token"

        return self.async_show_form(
            step_id=CONF_MQTT_URL,
            data_schema=vol.Schema({
                vol.Required(CONF_MQTT_URL): str,
            }),
            errors=errors,
        )

    async def async_step_entity_types(self, user_input=None):
        """处理实体类型选择步骤。"""
        return await self._async_handle_entity_types_step(user_input)
        
    async def async_step_entities(self, user_input=None):
        """处理实体选择步骤。"""
        async def _process_result(entities):
            """处理选定的实体列表。"""
            self._entities = entities
            data = self._get_connection_data()
            data[CONF_ENTITIES] = entities
            
            # 生成自定义标题
            title = self._generate_title()
            
            return self.async_create_entry(title=title, data=data)
            
        return await self._async_handle_entities_step(user_input, _process_result)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """获取选项流程。"""
        return MqttSyncOptionsFlowHandler(config_entry)


class MqttSyncOptionsFlowHandler(config_entries.OptionsFlow, MqttSyncFlowMixin):
    """处理MQTT同步选项流程。"""

    def __init__(self, config_entry):
        """初始化选项处理程序。"""
        super().__init__()
        MqttSyncFlowMixin.__init__(self)
        
        # 从配置项中加载数据
        data = config_entry.data
        self._entity_types = data.get(CONF_ENTITY_TYPES, [])
        self._mqtt_url = data.get("mqtt_url")
        self._mqtt_port = data.get("mqtt_port")
        self._web_url = data.get("web_url")
        self._username = data.get("username")
        self._password = data.get("password")

    async def async_step_init(self, user_input=None):
        """处理初始步骤。"""
        return await self.async_step_entity_types()

    async def async_step_entity_types(self, user_input=None):
        """处理实体类型选择步骤。"""
        return await self._async_handle_entity_types_step(user_input, self._entity_types)

    async def async_step_entities(self, user_input=None):
        """处理实体选择步骤。"""
        current_entities = self.config_entry.data.get(CONF_ENTITIES, [])
        
        async def _process_result(entities):
            """处理选定的实体列表。"""
            # 更新配置项，保留所有MQTT连接信息
            new_data = self._get_connection_data()
            new_data[CONF_ENTITIES] = entities
            
            # 更新配置项时保留原有标题
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            return self.async_create_entry(title="", data={})
            
        return await self._async_handle_entities_step(
            user_input, _process_result, current_entities
        ) 