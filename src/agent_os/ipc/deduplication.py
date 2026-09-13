from collections import OrderedDict
import asyncio

class DeduplicationFilter:
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self.seen_ids: OrderedDict[str, bool] = OrderedDict()
        self.lock = asyncio.Lock()
        
    async def is_duplicate(self, message_id: str) -> bool:
        async with self.lock:
            return message_id in self.seen_ids
            
    async def mark_seen(self, message_id: str) -> None:
        async with self.lock:
            if message_id in self.seen_ids:
                self.seen_ids.move_to_end(message_id)
            else:
                self.seen_ids[message_id] = True
                if len(self.seen_ids) > self.max_size:
                    self.seen_ids.popitem(last=False)
