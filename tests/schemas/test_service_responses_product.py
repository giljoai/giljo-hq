# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.service_responses import (
    CascadeImpact,
    GitIntegrationSettings,
    PathValidationResult,
    ProductStatistics,
    PurgeResult,
    VisionUploadResult,
)




class TestProductStatistics:

    def test_creation_with_required_fields(self):
        stats = ProductStatistics(product_id="p1", name="Test Product", is_active=True)
        assert stats.product_id == "p1"
        assert stats.name == "Test Product"
        assert stats.is_active is True
        assert stats.project_count == 0
        assert stats.task_count == 0
        assert stats.vision_documents_count == 0

    def test_creation_with_all_fields(self):
        stats = ProductStatistics(
            product_id="p2",
            name="Full Product",
            is_active=True,
            project_count=10,
            unfinished_projects=3,
            task_count=200,
            unresolved_tasks=45,
            vision_documents_count=15,
            has_vision=True,
        )
        assert stats.project_count == 10
        assert stats.unfinished_projects == 3
        assert stats.task_count == 200
        assert stats.unresolved_tasks == 45
        assert stats.vision_documents_count == 15
        assert stats.has_vision is True

    def test_missing_product_id_raises(self):
        with pytest.raises(ValidationError):
            ProductStatistics(name="P", is_active=True)

    def test_model_dump(self):
        stats = ProductStatistics(product_id="p", name="n", is_active=False, project_count=5)
        dumped = stats.model_dump()
        assert dumped["product_id"] == "p"
        assert dumped["project_count"] == 5
        assert dumped["task_count"] == 0

    def test_from_attributes_config(self):
        assert ProductStatistics.model_config.get("from_attributes") is True


class TestCascadeImpact:

    def test_creation_with_required_fields(self):
        impact = CascadeImpact(product_id="prod-123", product_name="Test Product")
        assert impact.product_id == "prod-123"
        assert impact.product_name == "Test Product"
        assert impact.total_projects == 0
        assert impact.total_tasks == 0
        assert impact.total_vision_documents == 0
        assert impact.warning == ""

    def test_missing_product_id_raises(self):
        with pytest.raises(ValidationError):
            CascadeImpact(product_name="P")

    def test_missing_product_name_raises(self):
        with pytest.raises(ValidationError):
            CascadeImpact(product_id="p1")

    def test_creation_with_counts(self):
        impact = CascadeImpact(
            product_id="prod-456",
            product_name="Test",
            total_projects=3,
            total_tasks=45,
            total_vision_documents=7,
            warning="This will delete all related data",
        )
        assert impact.total_projects == 3
        assert impact.total_tasks == 45
        assert impact.total_vision_documents == 7
        assert "delete" in impact.warning

    def test_model_dump(self):
        impact = CascadeImpact(product_id="p1", product_name="P", total_projects=2)
        dumped = impact.model_dump()
        assert dumped["product_id"] == "p1"
        assert dumped["total_projects"] == 2

    def test_from_attributes_config(self):
        assert CascadeImpact.model_config.get("from_attributes") is True


class TestVisionUploadResult:

    def test_creation_with_required_fields(self):
        result = VisionUploadResult(document_id="doc-1", document_name="design.pdf")
        assert result.document_id == "doc-1"
        assert result.document_name == "design.pdf"
        assert result.chunks_created == 0
        assert result.total_tokens == 0

    def test_missing_document_id_raises(self):
        with pytest.raises(ValidationError):
            VisionUploadResult(document_name="test.pdf")

    def test_missing_document_name_raises(self):
        with pytest.raises(ValidationError):
            VisionUploadResult(document_id="doc-1")

    def test_creation_with_all_fields(self):
        result = VisionUploadResult(
            document_id="doc-2",
            document_name="architecture.md",
            chunks_created=5,
            total_tokens=12000,
        )
        assert result.chunks_created == 5
        assert result.total_tokens == 12000

    def test_model_dump(self):
        result = VisionUploadResult(document_id="d", document_name="f.txt")
        dumped = result.model_dump()
        assert dumped["document_id"] == "d"
        assert dumped["document_name"] == "f.txt"
        assert dumped["chunks_created"] == 0

    def test_from_attributes_config(self):
        assert VisionUploadResult.model_config.get("from_attributes") is True


class TestPurgeResult:

    def test_creation_defaults(self):
        result = PurgeResult()
        assert result.purged_count == 0
        assert result.purged_ids == []

    def test_creation_with_values(self):
        result = PurgeResult(purged_count=3, purged_ids=["p1", "p2", "p3"])
        assert result.purged_count == 3
        assert len(result.purged_ids) == 3
        assert "p2" in result.purged_ids

    def test_purged_ids_default_factory_isolation(self):
        r1 = PurgeResult()
        r2 = PurgeResult()
        r1.purged_ids.append("x")
        assert "x" not in r2.purged_ids

    def test_model_dump(self):
        result = PurgeResult(purged_count=1, purged_ids=["abc"])
        dumped = result.model_dump()
        assert dumped["purged_count"] == 1
        assert dumped["purged_ids"] == ["abc"]

    def test_from_attributes_config(self):
        assert PurgeResult.model_config.get("from_attributes") is True


class TestPathValidationResult:

    def test_creation_with_required_fields(self):
        result = PathValidationResult(valid=True, path="/home/user/project")
        assert result.valid is True
        assert result.path == "/home/user/project"
        assert result.message == ""

    def test_invalid_path(self):
        result = PathValidationResult(
            valid=False,
            path="/nonexistent",
            message="Directory does not exist",
        )
        assert result.valid is False
        assert result.message == "Directory does not exist"

    def test_missing_valid_raises(self):
        with pytest.raises(ValidationError):
            PathValidationResult(path="/some/path")

    def test_missing_path_raises(self):
        with pytest.raises(ValidationError):
            PathValidationResult(valid=True)

    def test_model_dump(self):
        result = PathValidationResult(valid=True, path="/p", message="OK")
        dumped = result.model_dump()
        assert dumped == {"valid": True, "path": "/p", "message": "OK"}

    def test_from_attributes_config(self):
        assert PathValidationResult.model_config.get("from_attributes") is True


class TestGitIntegrationSettings:

    def test_creation_defaults(self):
        settings = GitIntegrationSettings()
        assert settings.enabled is False
        assert settings.repo_url is None
        assert settings.branch is None
        assert settings.auto_commit is False

    def test_creation_with_values(self):
        settings = GitIntegrationSettings(
            enabled=True,
            repo_url="https://github.com/org/repo.git",
            branch="main",
            auto_commit=True,
        )
        assert settings.enabled is True
        assert settings.repo_url == "https://github.com/org/repo.git"
        assert settings.branch == "main"
        assert settings.auto_commit is True

    def test_model_dump(self):
        settings = GitIntegrationSettings(enabled=True, branch="develop")
        dumped = settings.model_dump()
        assert dumped["enabled"] is True
        assert dumped["branch"] == "develop"
        assert dumped["repo_url"] is None

    def test_from_attributes_config(self):
        assert GitIntegrationSettings.model_config.get("from_attributes") is True
