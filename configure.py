"""Store a token locally without showing it or placing it in shell history."""
import getpass
import os
from pathlib import Path

def main():
    path = Path(__file__).resolve().parent / '.env.local'
    if path.exists() and input('已有本地配置，覆盖吗？输入 yes 才继续 ' ).strip() != 'yes':
        return
    value = getpass.getpass('粘贴自己的 OpenNews / OpenTwitter Token（输入不显示） ').strip()
    if not value or any(c.isspace() for c in value) or any(c in value for c in '\r\n\x00\"\''):
        raise SystemExit('Token 为空或含无效字符，未保存。')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write('OPENNEWS_TOKEN=' + value + '\n')
    if os.name == 'posix':path.chmod(0o600)
    print('已保存到本项目 .env.local；未显示 Token。重启阅读器后生效。')

if __name__ == '__main__':main()
