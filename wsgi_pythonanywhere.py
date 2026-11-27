import os
import sys

path = '/home/bradford7364123/CertDesk'
if path not in sys.path:
    sys.path.append(path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'certdesk.settings')

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()