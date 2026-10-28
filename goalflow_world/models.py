from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class Record(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Person(Record):
    id: str
    name: str
    company: str
    role: str
    contact: str
    can_decide: list[str] = []
    required_reviewer: bool = False

class Document(Record):
    id: str
    version: int = Field(ge=1)
    title: str
    body: str
    audience: Literal['internal', 'project'] = 'project'
    current: bool = True

class Message(Record):
    id: str
    sender: str
    recipient: str
    thread: str
    topic: str
    body: str
    authored_at: str
    delivered_at: str
    artifact_version: int | None = None
    subject: str | None = None
    decision: dict | None = None

class Task(Record):
    id: str
    title: str
    owner: str
    status: Literal['todo', 'in_progress', 'blocked', 'done', 'cancelled']
    acceptance: str
    source_ids: list[str] = []
    protected: bool = False
    artifact_version: int | None = Field(default=None, ge=1)
    change_key: Literal['form_layout', 'hero_copy', 'contrast', 'keyboard', 'headline'] | None = None
    change_value: str | None = None
    covers_requirements: list[Literal['contrast_required', 'keyboard_required']] = []

class World(Record):
    schema_version: Literal[1] = 1
    case_id: str
    company: str
    client: str
    project_id: str
    goal: str
    clock: str
    deadline: str
    timezone: str = 'America/New_York'
    required_reviewers: list[str]
    decision_maker: str
    current_artifact_version: int = 1
    people: list[Person]
    documents: list[Document]
    messages: list[Message]
    tasks: list[Task]

    @model_validator(mode='after')
    def references(self):
        ids = {p.id for p in self.people}
        if len(ids) != len(self.people):
            raise ValueError('Duplicate person ID')
        for collection in [self.messages, self.tasks]:
            keys = [r.id for r in collection]
            if len(keys) != len(set(keys)):
                raise ValueError('Duplicate record ID')
        docs = [(d.id, d.version) for d in self.documents]
        if len(docs) != len(set(docs)):
            raise ValueError('Duplicate document revision')
        if not set(self.required_reviewers) <= ids or self.decision_maker not in ids:
            raise ValueError('Unknown reviewer or decision authority')
        for m in self.messages:
            if m.sender not in ids or m.recipient not in ids:
                raise ValueError('Unknown message participant')
        for t in self.tasks:
            if t.owner not in ids:
                raise ValueError('Unknown task owner')
        return self

class Event(Record):
    id: str
    trigger: dict
    delay_business_minutes: int = Field(ge=0)
    kind: Literal['message', 'scope_change', 'version_change']
    payload: dict
