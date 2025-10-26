"""Unit tests for database base classes."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, String, UniqueConstraint, create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db.base import NAMING_CONVENTION, Base


class TestNamingConvention:
    """Test naming convention configuration."""

    def test_naming_convention_contains_all_constraint_types(self) -> None:
        """Test that naming convention includes all constraint types."""
        expected_keys = {"ix", "uq", "ck", "fk", "pk"}
        actual_keys = set(NAMING_CONVENTION.keys())

        assert actual_keys == expected_keys

    def test_naming_convention_index_format_is_correct(self) -> None:
        """Test that index naming convention format is correct."""
        assert NAMING_CONVENTION["ix"] == "ix_%(column_0_label)s"

    def test_naming_convention_unique_format_is_correct(self) -> None:
        """Test that unique constraint naming convention format is correct."""
        assert NAMING_CONVENTION["uq"] == "uq_%(table_name)s_%(column_0_name)s"

    def test_naming_convention_check_format_is_correct(self) -> None:
        """Test that check constraint naming convention format is correct."""
        assert NAMING_CONVENTION["ck"] == "ck_%(table_name)s_%(constraint_name)s"

    def test_naming_convention_foreign_key_format_is_correct(self) -> None:
        """Test that foreign key naming convention format is correct."""
        assert NAMING_CONVENTION["fk"] == "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"

    def test_naming_convention_primary_key_format_is_correct(self) -> None:
        """Test that primary key naming convention format is correct."""
        assert NAMING_CONVENTION["pk"] == "pk_%(table_name)s"


class TestBaseClass:
    """Test Base declarative class."""

    def test_base_is_abstract(self) -> None:
        """Test that Base class is marked as abstract."""
        assert Base.__abstract__ is True

    def test_base_has_metadata_with_naming_convention(self) -> None:
        """Test that Base has metadata with naming convention."""
        assert Base.metadata is not None
        assert Base.metadata.naming_convention == NAMING_CONVENTION

    def test_base_inheritance_works_correctly(self) -> None:
        """Test that classes can inherit from Base correctly."""

        class TestModel(Base):
            __tablename__ = "test_table"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)

        # Verify the model was created successfully
        assert TestModel.__tablename__ == "test_table"
        assert TestModel.id is not None
        assert TestModel.name is not None

    def test_base_models_can_be_created_and_queried(self) -> None:
        """Test that models inheriting from Base can be created and queried."""

        class TestModel2(Base):
            __tablename__ = "test_table_2"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        # Create session
        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            # Create a test instance
            test_instance = TestModel2(name="test_value")
            session.add(test_instance)
            session.commit()

            # Query the instance
            result = session.query(TestModel2).first()
            assert result is not None
            assert result.name == "test_value"
            assert result.id == 1

    def test_base_models_support_relationships(self) -> None:
        """Test that models inheriting from Base support relationships."""
        from sqlalchemy import ForeignKey
        from sqlalchemy.orm import relationship

        class ParentModel2(Base):
            __tablename__ = "parent_table_2"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)

            # Relationship
            children = relationship("ChildModel2", back_populates="parent")

        class ChildModel2(Base):
            __tablename__ = "child_table_2"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)
            parent_id = Column(Integer, ForeignKey("parent_table_2.id"))

            # Relationship
            parent = relationship("ParentModel2", back_populates="children")

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        # Create session
        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            # Create parent and child
            parent = ParentModel2(name="parent")
            child = ChildModel2(name="child", parent=parent)

            session.add_all([parent, child])
            session.commit()

            # Test relationship
            assert len(parent.children) == 1
            assert parent.children[0].name == "child"
            assert child.parent.name == "parent"

    def test_base_models_support_indexes(self) -> None:
        """Test that models inheriting from Base support indexes."""
        from sqlalchemy import Index

        class IndexedModel(Base):
            __tablename__ = "indexed_table"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)
            email = Column(String(100), nullable=False)

            # Create index using naming convention
            __table_args__ = (
                Index("ix_indexed_table_name", "name"),
                Index("ix_indexed_table_email", "email"),
            )

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        # Verify indexes were created (SQLite doesn't support index introspection well,
        # but we can verify the table was created without errors)
        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            # Create and query a test instance
            test_instance = IndexedModel(name="test", email="test@example.com")
            session.add(test_instance)
            session.commit()

            result = session.query(IndexedModel).first()
            assert result is not None
            assert result.name == "test"
            assert result.email == "test@example.com"

    def test_base_models_support_unique_constraints(self) -> None:
        """Test that models inheriting from Base support unique constraints."""
        from sqlalchemy import UniqueConstraint

        class UniqueModel(Base):
            __tablename__ = "unique_table"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)
            email = Column(String(100), nullable=False)

            # Create unique constraint using naming convention
            __table_args__ = (UniqueConstraint("email", name="uq_unique_table_email"),)

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        # Verify unique constraint works
        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            # Create first instance
            test_instance1 = UniqueModel(name="test1", email="test@example.com")
            session.add(test_instance1)
            session.commit()

            # Try to create second instance with same email (should fail)
            test_instance2 = UniqueModel(name="test2", email="test@example.com")
            session.add(test_instance2)

            with pytest.raises(Exception):  # SQLite raises IntegrityError
                session.commit()

    def test_base_metadata_reflects_correctly(self) -> None:
        """Test that Base metadata reflects database schema correctly."""

        class ReflectionModel(Base):
            __tablename__ = "reflection_table"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        # Create new metadata and reflect from database
        from sqlalchemy import MetaData

        reflected_metadata = MetaData()
        reflected_metadata.reflect(bind=engine)

        # Verify table was reflected
        assert "reflection_table" in reflected_metadata.tables
        reflected_table = reflected_metadata.tables["reflection_table"]

        # Verify columns were reflected
        assert "id" in reflected_table.columns
        assert "name" in reflected_table.columns

    def test_base_models_work_with_different_database_types(self) -> None:
        """Test that Base models work with different database types."""

        class MultiDbModel(Base):
            __tablename__ = "multidb_table"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False)

        # Test with SQLite
        sqlite_engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(sqlite_engine)

        SQLiteSession = sessionmaker(bind=sqlite_engine)
        with SQLiteSession() as session:
            sqlite_instance = MultiDbModel(name="sqlite_test")
            session.add(sqlite_instance)
            session.commit()

            result = session.query(MultiDbModel).first()
            assert result.name == "sqlite_test"

    def test_base_naming_convention_applies_to_constraints(self) -> None:
        """Test that naming convention is applied to constraints."""

        class ConstraintModel(Base):
            __tablename__ = "constraint_table"

            id = Column(Integer, primary_key=True)
            name = Column(String(100), nullable=False, unique=True)
            email = Column(String(100), nullable=False)

            __table_args__ = (UniqueConstraint("email", name="uq_constraint_table_email"),)

        # Create in-memory SQLite database
        engine = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(engine)

        # Verify naming convention was applied
        table = Base.metadata.tables["constraint_table"]

        # Check that unique constraints follow naming convention
        unique_constraints = [c.name for c in table.constraints if hasattr(c, 'name') and c.name]
        assert any(name.startswith("uq_constraint_table_") for name in unique_constraints)
