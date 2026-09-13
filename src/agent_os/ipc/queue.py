import asyncio
from typing import Dict
from agent_os.ipc.channel import Channel
from agent_os.ipc.message import Message

class MessageQueue:
    def __init__(self, capacity: int, overflow_policy: str = 'BLOCK'):
        self.capacity = capacity
        self.overflow_policy = overflow_policy
        self.channels: Dict[int, Channel] = {}
        self.lock = asyncio.Lock()
        self.not_empty = asyncio.Event()
        self.not_full = asyncio.Event()
        self.not_full.set()
        
    def count(self) -> int:
        return sum(len(ch) for ch in self.channels.values())
        
    async def send(self, message: Message) -> bool:
        if self.overflow_policy == 'BLOCK':
            while True:
                async with self.lock:
                    if self.count() < self.capacity:
                        break
                await self.not_full.wait()
        else:
            async with self.lock:
                if self.count() >= self.capacity:
                    if self.overflow_policy == 'REJECT':
                        return False
                    elif self.overflow_policy == 'DROP':
                        # Find oldest message across all channels and drop it
                        oldest_msg = None
                        target_ch = None
                        for ch in self.channels.values():
                            msg = ch.peek()
                            if msg:
                                if oldest_msg is None or msg.timestamp < oldest_msg.timestamp:
                                    oldest_msg = msg
                                    target_ch = ch
                        if target_ch:
                            target_ch.receive()
                            
        async with self.lock:
            sender_pid = message.sender_pid
            if sender_pid not in self.channels:
                self.channels[sender_pid] = Channel(sender_pid, message.receiver_pid)
                
            self.channels[sender_pid].send(message)
            self.not_empty.set()
            
            if self.count() >= self.capacity:
                self.not_full.clear()
            return True

    async def receive(self, receiver_pid: int) -> Message | None:
        async with self.lock:
            oldest_msg = None
            target_ch = None
            for ch in self.channels.values():
                msg = ch.peek()
                if msg:
                    if oldest_msg is None or msg.timestamp < oldest_msg.timestamp:
                        oldest_msg = msg
                        target_ch = ch
                        
            if target_ch:
                msg = target_ch.receive()
                if self.count() == 0:
                    self.not_empty.clear()
                if self.count() < self.capacity:
                    self.not_full.set()
                return msg
                
        return None
        
    async def wait_for_message(self, receiver_pid: int) -> Message:
        while True:
            await self.not_empty.wait()
            msg = await self.receive(receiver_pid)
            if msg is not None:
                return msg
