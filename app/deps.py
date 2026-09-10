from fastapi import Request

from app.service import UrjaService


def get_service(request: Request) -> UrjaService:
    return request.app.state.service
