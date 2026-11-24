# -*- coding: utf-8 -*-
import os
import itasca_mcp_bridge
port = int(os.environ['ITASCA_MCP_BRIDGE_PORT'])
itasca_mcp_bridge.start(host='127.0.0.1', port=port, mode='console', auto_upgrade=False)
