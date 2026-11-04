# engine/__init__.py
"""进程入口的初始化:任何 engine.* 子模块被导入之前先跑一遍。

httpx 会把 NO_PROXY 里 [::1] 这类带方括号的条目当成「主机:端口」解析并抛
InvalidURL。litellm、githubkit 等第三方库都在 import 期构造 httpx 客户端,
所以规范化必须发生在最早的位置——这里,而不是各个 client 的构造函数里。
"""

from engine.shared.netenv import prepare_proxy_env as _prepare_proxy_env

_prepare_proxy_env()
