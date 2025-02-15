from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    ForeignKey,
    Boolean,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

Base = declarative_base()


class Topic(Base):
    __tablename__ = "topics"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    questions = relationship("Question", back_populates="topic")


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"))
    text = Column(String, nullable=False)
    topic = relationship("Topic", back_populates="questions")
    options = relationship("QuestionOption", back_populates="question")


class QuestionOption(Base):
    __tablename__ = "question_options"

    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey("questions.id"))
    text = Column(String, nullable=False)
    is_correct = Column(Boolean, default=False)
    question = relationship("Question", back_populates="options")


def init_db():
    engine = create_engine(
        "sqlite:///data/test_bot.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()
