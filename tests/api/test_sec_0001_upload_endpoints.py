# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest

from giljo_mcp.models.products import Product


ENDPOINT_A = "/api/vision-documents/"
ENDPOINT_B_TEMPLATE = "/api/v1/products/{product_id}/vision"




async def _seed_product(db_manager, tenant_key: str) -> str:
    async with db_manager.get_session_async() as session:
        product = Product(
            id=str(uuid4()),
            tenant_key=tenant_key,
            name="SEC-0001 Upload Target",
            description="fixture product for upload guardrail tests",
        )
        session.add(product)
        await session.commit()
        return str(product.id)


def _extract_tenant_key(auth_headers: dict) -> str:
    import base64
    import json

    cookie = auth_headers["Cookie"]
    access_segment = next(p for p in cookie.split(";") if p.strip().startswith("access_token="))
    token = access_segment.split("=", 1)[1]
    payload_b64 = token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))["tenant_key"]




class TestEndpointBFilenameSanitization:

    @pytest.mark.asyncio
    async def test_rejects_path_traversal_filename(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        files = {"file": ("../../etc/passwd", b"harmless text\n", "text/plain")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 400, response.text
        body = response.json()
        assert body["error_code"] == "UPLOAD_FILENAME_INVALID"

    @pytest.mark.asyncio
    async def test_rejects_leading_dot_filename(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        files = {"file": (".hiddenrc.md", b"# hidden\n", "text/markdown")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 400, response.text
        assert response.json()["error_code"] == "UPLOAD_FILENAME_INVALID"


class TestEndpointBExtensionAllowlist:

    @pytest.mark.asyncio
    async def test_rejects_docx_extension_as_unsupported(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        files = {
            "file": (
                "report.docx",
                b"PK\x03\x04\x14\x00\x08",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 415, response.text
        body = response.json()
        assert body["error_code"] == "UPLOAD_TYPE_NOT_ALLOWED"
        assert ".txt" in body["context"]["allowed_extensions"]


class TestEndpointBByteSniff:

    @pytest.mark.asyncio
    async def test_rejects_pdf_spoofed_as_txt(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<\n/Type /Catalog\n>>"
        files = {"file": ("fake.txt", pdf_bytes, "text/plain")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 415, response.text
        assert response.json()["error_code"] == "UPLOAD_CONTENT_NOT_TEXT"

    @pytest.mark.asyncio
    async def test_rejects_png_spoofed_as_md(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 32
        files = {"file": ("image.md", png_bytes, "text/markdown")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 415, response.text
        assert response.json()["error_code"] == "UPLOAD_CONTENT_NOT_TEXT"


class TestEndpointBSizeCap:

    @pytest.mark.asyncio
    async def test_content_length_precheck_rejects_oversize_upload(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        oversize_body = b"a" * (5 * 1024 * 1024 + 1024)
        files = {"file": ("big.txt", oversize_body, "text/plain")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id),
            headers=auth_headers,
            files=files,
        )

        assert response.status_code == 413, response.text
        body = response.json()
        assert body["error_code"] == "UPLOAD_TOO_LARGE"
        assert body["context"]["max_bytes"] == 5 * 1024 * 1024


class TestEndpointBRegression:

    @pytest.mark.asyncio
    async def test_legitimate_markdown_upload_succeeds(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        payload = b"# SEC-0001\n\nLegitimate markdown content.\n"
        files = {"file": ("notes.md", payload, "text/markdown")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["success"] is True
        assert body["document_name"] == "notes.md"

    @pytest.mark.asyncio
    async def test_legitimate_txt_upload_succeeds(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        payload = b"Plain text vision document.\n"
        files = {"file": ("vision.txt", payload, "text/plain")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 201, response.text
        assert response.json()["document_name"] == "vision.txt"

    @pytest.mark.asyncio
    async def test_legitimate_markdown_long_extension_succeeds(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        payload = b"# Heading\nMarkdown body.\n"
        files = {"file": ("notes.markdown", payload, "text/markdown")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=product_id), headers=auth_headers, files=files
        )

        assert response.status_code == 201, response.text
        assert response.json()["document_name"] == "notes.markdown"


async def _vision_doc_count(db_manager, tenant_key: str, product_id: str) -> int:
    from sqlalchemy import func, select

    from giljo_mcp.models.products import VisionDocument

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        stmt = (
            select(func.count())
            .select_from(VisionDocument)
            .where(VisionDocument.product_id == product_id, VisionDocument.tenant_key == tenant_key)
        )
        return int((await session.execute(stmt)).scalar_one())


class TestEndpointBNoOrphanDocument:

    @pytest.mark.asyncio
    async def test_blank_upload_is_refused_and_leaves_no_row(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)
        url = ENDPOINT_B_TEMPLATE.format(product_id=product_id)

        first = await api_client.post(
            url, headers=auth_headers, files={"file": ("blank.md", b"   \n\n", "text/markdown")}
        )
        assert first.status_code == 400, first.text
        assert await _vision_doc_count(db_manager, tenant_key, product_id) == 0

        retry = await api_client.post(
            url, headers=auth_headers, files={"file": ("blank.md", b"   \n\n", "text/markdown")}
        )
        assert retry.status_code == 400, retry.text

    @pytest.mark.asyncio
    async def test_chunking_failure_leaves_no_row(self, api_client, auth_headers, db_manager):
        from unittest.mock import AsyncMock, patch

        from giljo_mcp.exceptions import ContextError

        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)
        url = ENDPOINT_B_TEMPLATE.format(product_id=product_id)
        files = {"file": ("vision.md", b"# Vision\n\nReal content.\n", "text/markdown")}

        with patch(
            "giljo_mcp.context_management.chunker.VisionDocumentChunker.chunk_vision_document",
            AsyncMock(side_effect=ContextError("chunker down")),
        ):
            failed = await api_client.post(url, headers=auth_headers, files=files)
        assert failed.status_code == 500, failed.text
        assert await _vision_doc_count(db_manager, tenant_key, product_id) == 0

        retry = await api_client.post(url, headers=auth_headers, files=files)
        assert retry.status_code == 201, retry.text




class TestEndpointAFilenameSanitization:

    @pytest.mark.asyncio
    async def test_rejects_path_traversal_filename(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        data = {
            "product_id": product_id,
            "document_name": "Roadmap",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {"vision_file": ("../../boot.ini", b"some text", "text/plain")}

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 400, response.text
        body = response.json()
        assert body["error_code"] == "UPLOAD_FILENAME_INVALID"


class TestEndpointAExtensionAllowlist:

    @pytest.mark.asyncio
    async def test_rejects_docx_extension_as_unsupported(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        data = {
            "product_id": product_id,
            "document_name": "Spec",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {
            "vision_file": (
                "spec.docx",
                b"PK\x03\x04\x14\x00\x08",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 415, response.text
        assert response.json()["error_code"] == "UPLOAD_TYPE_NOT_ALLOWED"


class TestEndpointAByteSniff:

    @pytest.mark.asyncio
    async def test_rejects_pdf_spoofed_as_txt(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        pdf_bytes = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<\n/Type /Catalog\n>>"

        data = {
            "product_id": product_id,
            "document_name": "Fake",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {"vision_file": ("fake.txt", pdf_bytes, "text/plain")}

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 415, response.text
        assert response.json()["error_code"] == "UPLOAD_CONTENT_NOT_TEXT"

    @pytest.mark.asyncio
    async def test_rejects_latin1_windows_file(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        latin1_payload = b"Temperature: 72\xb0F ambient.\n"

        data = {
            "product_id": product_id,
            "document_name": "Telemetry",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {"vision_file": ("telemetry.txt", latin1_payload, "text/plain")}

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 415, response.text
        assert response.json()["error_code"] == "UPLOAD_CONTENT_NOT_TEXT"


class TestEndpointASizeCap:

    @pytest.mark.asyncio
    async def test_rejects_oversize_upload(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        oversize_body = b"a" * (5 * 1024 * 1024 + 1024)

        data = {
            "product_id": product_id,
            "document_name": "Oversize",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {"vision_file": ("big.txt", oversize_body, "text/plain")}

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 413, response.text
        body = response.json()
        assert body["error_code"] == "UPLOAD_TOO_LARGE"
        assert body["context"]["max_bytes"] == 5 * 1024 * 1024


class TestEndpointARegression:

    @pytest.mark.asyncio
    async def test_legitimate_markdown_upload_succeeds(self, api_client, auth_headers, db_manager, tmp_path):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        payload = b"# Roadmap\n\n- Q1 deliverable\n- Q2 deliverable\n"
        data = {
            "product_id": product_id,
            "document_name": "Roadmap",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {"vision_file": ("roadmap.md", payload, "text/markdown")}

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["document_name"] == "Roadmap"
        assert body["tenant_key"] == tenant_key

    @pytest.mark.asyncio
    async def test_inline_content_branch_unaffected(self, api_client, auth_headers, db_manager):
        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        data = {
            "product_id": product_id,
            "document_name": "Inline",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
            "content": "Inline text content for the inline-only branch.",
        }
        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data)

        assert response.status_code == 201, response.text




class TestTenantIsolation:

    @pytest.mark.asyncio
    async def test_endpoint_b_rejects_cross_tenant_product(self, api_client, auth_headers, db_manager):
        other_tenant = "tk_" + uuid4().hex[:32]
        async with db_manager.get_session_async() as session:
            other_product = Product(
                id=str(uuid4()),
                tenant_key=other_tenant,
                name="Foreign Product",
                description="owned by another tenant",
            )
            session.add(other_product)
            await session.commit()
            foreign_product_id = str(other_product.id)

        files = {"file": ("vision.md", b"# cross-tenant\n", "text/markdown")}
        response = await api_client.post(
            ENDPOINT_B_TEMPLATE.format(product_id=foreign_product_id),
            headers=auth_headers,
            files=files,
        )

        assert response.status_code != 201, response.text
        assert 400 <= response.status_code < 500, response.text




class TestBe5115EndpointAInlineOnly:

    @pytest.mark.asyncio
    async def test_file_upload_stores_inline_and_does_not_write_to_disk(self, api_client, auth_headers, db_manager):
        from sqlalchemy import select

        from giljo_mcp.models import VisionDocument

        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        payload = b"BE-5115 inline-only upload.\nSecond line.\n"
        data = {
            "product_id": product_id,
            "document_name": "be5115_vision",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
        }
        files = {"vision_file": ("be5115_vision.md", payload, "text/markdown")}

        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data, files=files)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["storage_type"] == "inline"
        assert not body.get("vision_path"), f"vision_path must be empty/null, got {body.get('vision_path')!r}"

        async with db_manager.get_session_async() as session:
            session.info["tenant_key"] = tenant_key
            result = await session.execute(
                select(VisionDocument).where(VisionDocument.id == body["id"]),
            )
            doc = result.scalar_one_or_none()
        assert doc is not None, "uploaded vision document not found in DB"
        assert doc.storage_type == "inline"
        assert doc.vision_path is None
        assert doc.vision_document == payload.decode("utf-8")

    @pytest.mark.asyncio
    async def test_inline_content_upload_stores_inline_with_null_vision_path(
        self, api_client, auth_headers, db_manager
    ):
        from sqlalchemy import select

        from giljo_mcp.models import VisionDocument

        tenant_key = _extract_tenant_key(auth_headers)
        product_id = await _seed_product(db_manager, tenant_key)

        inline_text = "BE-5115 inline branch - no file attached."
        data = {
            "product_id": product_id,
            "document_name": "be5115_inline",
            "document_type": "vision",
            "version": "1.0.0",
            "display_order": "0",
            "content": inline_text,
        }
        response = await api_client.post(ENDPOINT_A, headers=auth_headers, data=data)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["storage_type"] == "inline"

        async with db_manager.get_session_async() as session:
            session.info["tenant_key"] = tenant_key
            result = await session.execute(
                select(VisionDocument).where(VisionDocument.id == body["id"]),
            )
            doc = result.scalar_one_or_none()
        assert doc is not None
        assert doc.storage_type == "inline"
        assert doc.vision_path is None
        assert doc.vision_document == inline_text
