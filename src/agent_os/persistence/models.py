"""Agent-OS Persistence — Models."""
from sqlalchemy import Column, Integer, String, Float, Boolean
from agent_os.persistence.database import Base

class ProcessRecord(Base):
    __tablename__ = 'processes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    process_id = Column(Integer, unique=True, index=True)
    name = Column(String)
    state = Column(String)
    priority = Column(Integer)
    weight = Column(Integer)
    parent_process_id = Column(Integer, nullable=True)
    restart_count = Column(Integer, default=0)
    failure_count = Column(Integer, default=0)
    creation_time = Column(Float)
    start_time = Column(Float, nullable=True)
    completion_time = Column(Float, nullable=True)

class ProcessMetricRecord(Base):
    __tablename__ = 'process_metrics'
    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, index=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    llm_calls = Column(Integer, default=0)
    tool_calls = Column(Integer, default=0)
    steps = Column(Integer, default=0)
    execution_time = Column(Float, default=0)
    waiting_time = Column(Float, default=0)
    turnaround_time = Column(Float, default=0)
    context_swaps = Column(Integer, default=0)
    timestamp = Column(Float)

class ContextPageRecord(Base):
    __tablename__ = 'context_pages'
    id = Column(Integer, primary_key=True)
    page_id = Column(String, unique=True)
    process_id = Column(Integer, index=True)
    page_index = Column(Integer)
    content_reference = Column(String, default='')
    loaded = Column(Boolean, default=True)
    pinned = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    last_accessed = Column(Float)

class CheckpointRecord(Base):
    __tablename__ = 'checkpoints'
    id = Column(Integer, primary_key=True)
    checkpoint_id = Column(String, unique=True)
    process_id = Column(Integer, index=True)
    process_state = Column(String)
    context_id = Column(String)
    context_version = Column(Integer)
    resource_usage_json = Column(String, default='{}')
    agent_state_json = Column(String, default='{}')
    timestamp = Column(Float)

class MessageRecord(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    message_id = Column(String, unique=True)
    sender_pid = Column(Integer)
    receiver_pid = Column(Integer)
    sequence_number = Column(Integer)
    correlation_id = Column(String, nullable=True)
    message_type = Column(String)
    payload_json = Column(String, default='{}')
    delivery_status = Column(String)
    timestamp = Column(Float)

class EventRecord(Base):
    __tablename__ = 'events'
    id = Column(Integer, primary_key=True)
    event_id = Column(String, unique=True)
    event_type = Column(String)
    process_id = Column(Integer, nullable=True)
    metadata_json = Column(String, default='{}')
    timestamp = Column(Float)

class ResourceUsageRecord(Base):
    __tablename__ = 'resource_usage'
    id = Column(Integer, primary_key=True)
    process_id = Column(Integer, index=True)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    total_tokens = Column(Integer)
    llm_calls = Column(Integer)
    tool_calls = Column(Integer)
    steps = Column(Integer)
    execution_time = Column(Float)
    timestamp = Column(Float)

class FailureDBRecord(Base):
    __tablename__ = 'failures'
    id = Column(Integer, primary_key=True)
    failure_id = Column(String, unique=True)
    process_id = Column(Integer, index=True)
    failure_type = Column(String)
    error_message = Column(String, default='')
    context_json = Column(String, nullable=True)
    timestamp = Column(Float)
