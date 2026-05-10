import { NextRequest, NextResponse } from "next/server";

import { getBackendApiUrl } from "@/lib/backend-api";

const ADMIN_API_TOKEN = process.env.ADMIN_API_TOKEN;

function backendHeaders(init?: HeadersInit): Headers {
    const headers = new Headers(init);
    if (ADMIN_API_TOKEN) {
        headers.set("X-Admin-Token", ADMIN_API_TOKEN);
    }
    return headers;
}

export async function GET(request: Request) {
    try {
        const url = new URL(request.url);
        const provider = url.searchParams.get("provider");
        let backendUrl = `${getBackendApiUrl()}/api/v1/admin/openai-secrets`;
        if (provider) {
            backendUrl += `?provider=${encodeURIComponent(provider)}`;
        }
        const response = await fetch(backendUrl, {
            cache: "no-store",
            headers: backendHeaders(),
        });
        if (!response.ok) {
            return NextResponse.json({ error: "Backend API error" }, { status: response.status });
        }
        return NextResponse.json(await response.json());
    } catch {
        return NextResponse.json({ error: "Failed to load cloud API key status" }, { status: 503 });
    }
}

export async function PUT(request: NextRequest) {
    try {
        const body = await request.json();
        const url = new URL(request.url);
        const provider = url.searchParams.get("provider");
        let backendUrl = `${getBackendApiUrl()}/api/v1/admin/openai-secrets`;
        if (provider) {
            backendUrl += `?provider=${encodeURIComponent(provider)}`;
        }
        const response = await fetch(backendUrl, {
            method: "PUT",
            headers: backendHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            const payload = await response.json().catch(() => ({}));
            return NextResponse.json(payload, { status: response.status });
        }
        return NextResponse.json(await response.json());
    } catch {
        return NextResponse.json({ error: "Failed to save API key" }, { status: 503 });
    }
}

export async function DELETE(request: Request) {
    try {
        const url = new URL(request.url);
        const provider = url.searchParams.get("provider");
        let backendUrl = `${getBackendApiUrl()}/api/v1/admin/openai-secrets`;
        if (provider) {
            backendUrl += `?provider=${encodeURIComponent(provider)}`;
        }
        const response = await fetch(backendUrl, {
            method: "DELETE",
            headers: backendHeaders(),
        });
        if (!response.ok) {
            return NextResponse.json({ error: "Backend API error" }, { status: response.status });
        }
        return NextResponse.json(await response.json());
    } catch {
        return NextResponse.json({ error: "Failed to clear API key" }, { status: 503 });
    }
}