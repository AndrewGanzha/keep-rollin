from typing import Protocol, TypeVar

RequestT = TypeVar("RequestT", contravariant=True)
ResponseT = TypeVar("ResponseT", covariant=True)


class IHandler(Protocol[RequestT, ResponseT]):
    async def handle(self, request: RequestT) -> ResponseT: ...
