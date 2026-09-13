from collections import deque
from agent_os.ipc.message import Message

class Channel:
    def __init__(self, sender_pid: int, receiver_pid: int):
        self.sender_pid = sender_pid
        self.receiver_pid = receiver_pid
        self.queue: deque[Message] = deque()
        self.next_sequence_number = 0
        
    def send(self, message: Message) -> None:
        message.sequence_number = self.next_sequence_number
        self.next_sequence_number += 1
        self.queue.append(message)
        
    def receive(self) -> Message | None:
        if self.queue:
            return self.queue.popleft()
        return None
        
    def peek(self) -> Message | None:
        if self.queue:
            return self.queue[0]
        return None
        
    def __len__(self) -> int:
        return len(self.queue)
        
    def is_empty(self) -> bool:
        return len(self.queue) == 0
