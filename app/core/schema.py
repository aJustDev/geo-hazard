from pydantic import BaseModel, ConfigDict


class BaseSchema(BaseModel):
    """Base for all DTOs. `from_attributes` lets routers do
    `ReadSchema.model_validate(orm_object)`."""

    model_config = ConfigDict(from_attributes=True)
