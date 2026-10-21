from __future__ import annotations

import uvicorn

from .app import create_app
from .config import WebSettings


def main() -> None:
    settings = WebSettings.from_env()
    application = create_app(settings)
    host = settings.host
    print(f"DoorCard web interface: http://{host}:{settings.port}")
    uvicorn.run(application, host=host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
