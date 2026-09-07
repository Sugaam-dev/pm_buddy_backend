import pytest
from uuid import uuid4

from app.core.database import AsyncSessionLocal
from app.models.entities import Organization, Project, Task, TaskDependency
from app.services.dependency_service import DependencyService


@pytest.mark.asyncio
async def test_dependency_creation_and_query():
    async with AsyncSessionLocal() as session:
        org_id = uuid4()
        org = Organization(id=org_id, name="Dep Test Org", slug=f"dep-org-{org_id.hex[:8]}")
        session.add(org)

        proj = Project(
            id=uuid4(),
            organization_id=org_id,
            name="Dep Project",
            key="DEP",
            owner_id=uuid4(),
        )
        session.add(proj)

        t1 = Task(id=uuid4(), organization_id=org_id, project_id=proj.id, title="Task 1 (Prerequisite)", status="todo")
        t2 = Task(id=uuid4(), organization_id=org_id, project_id=proj.id, title="Task 2 (Blocked)", status="todo")
        t3 = Task(id=uuid4(), organization_id=org_id, project_id=proj.id, title="Task 3 (Successor of 2)", status="todo")
        session.add_all([t1, t2, t3])
        await session.commit()

        # Add dependency: Task 2 depends on Task 1
        dep1 = await DependencyService.add_dependency(
            session=session,
            organization_id=org_id,
            project_id=proj.id,
            task_id=t2.id,
            depends_on_task_id=t1.id,
        )
        assert dep1.id is not None

        # Add dependency: Task 3 depends on Task 2
        dep2 = await DependencyService.add_dependency(
            session=session,
            organization_id=org_id,
            project_id=proj.id,
            task_id=t3.id,
            depends_on_task_id=t2.id,
        )
        assert dep2.id is not None

        # Query dependencies for Task 2
        deps_t2 = await DependencyService.get_task_dependencies(session, org_id, t2.id)
        assert len(deps_t2["predecessors"]) == 1
        assert deps_t2["predecessors"][0]["task_id"] == str(t1.id)
        assert len(deps_t2["successors"]) == 1
        assert deps_t2["successors"][0]["task_id"] == str(t3.id)
        assert deps_t2["is_blocked"] is True

        # Test Blocker list
        blockers = await DependencyService.get_blockers(session, org_id, proj.id)
        assert len(blockers) >= 1

        # Test Circular Dependency Prevention: Trying to make Task 1 depend on Task 3 should fail!
        with pytest.raises(ValueError) as exc_info:
            await DependencyService.add_dependency(
                session=session,
                organization_id=org_id,
                project_id=proj.id,
                task_id=t1.id,
                depends_on_task_id=t3.id,
            )
        assert "Circular dependency" in str(exc_info.value)

        # Cleanup
        await DependencyService.remove_dependency(session, org_id, dep1.id)
        await DependencyService.remove_dependency(session, org_id, dep2.id)
        await session.delete(t3)
        await session.delete(t2)
        await session.delete(t1)
        await session.delete(proj)
        await session.delete(org)
        await session.commit()
