// Centralized API client for Tajik HTR Studio
// Communicates with backend using anonymous session ID in X-Session-ID header

export function getOrCreateSessionId(): string {
  if (typeof window === 'undefined') return 'default-session';
  let id = localStorage.getItem('htr_session_id');
  if (!id) {
    id = (typeof crypto !== 'undefined' && crypto.randomUUID)
      ? crypto.randomUUID()
      : 's-' + Math.random().toString(36).substring(2) + Date.now().toString(36);
    localStorage.setItem('htr_session_id', id);
  }
  return id;
}

const API_BASE = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const sessionId = getOrCreateSessionId();
  const headers = new Headers(options.headers || {});
  
  headers.set('X-Session-ID', sessionId);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }

  const url = `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status} ${response.statusText}`;
    try {
      const errBody = await response.json();
      if (errBody.message) errorMessage = errBody.message;
      else if (errBody.detail) errorMessage = typeof errBody.detail === 'string' ? errBody.detail : JSON.stringify(errBody.detail);
    } catch {
      // ignore json parse error
    }
    throw new Error(errorMessage);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

export interface ApiDocument {
  id: string;
  title: string;
  status: 'draft' | 'processing' | 'ready' | 'error';
  page_count: number;
  created_at: string;
  updated_at: string;
  preview_url?: string;
  preview_text?: string;
}

export interface UploadResult {
  document_id: string;
  page_id: string;
  asset: {
    id: string;
    media_type: string;
    width: number;
    height: number;
    preview_url: string;
  };
}

export interface RecognitionResult {
  document_id: string;
  page_id: string;
  raw_text: string;
  lines: Array<{
    id: string;
    position: number;
    text: string;
  }>;
}

export const api = {
  async listDocuments(): Promise<ApiDocument[]> {
    try {
      const res = await request<{ items: ApiDocument[] }>('/api/v1/documents');
      return res.items || [];
    } catch (err) {
      console.warn('Backend listDocuments failed, fallback to local store', err);
      return [];
    }
  },

  async getDocument(documentId: string): Promise<any> {
    return request<any>(`/api/v1/documents/${documentId}`);
  },

  async uploadFile(file: File): Promise<UploadResult> {
    const sessionId = getOrCreateSessionId();
    const url = `${API_BASE}/api/v1/documents/upload`;

    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'X-Session-ID': sessionId,
        'Content-Type': file.type || 'image/png',
        'X-Original-Filename': encodeURIComponent(file.name),
      },
      body: file,
    });

    if (!response.ok) {
      let msg = `Upload failed: ${response.statusText}`;
      try {
        const data = await response.json();
        if (data.message) msg = data.message;
      } catch {}
      throw new Error(msg);
    }

    return response.json();
  },

  async recognizeDocument(documentId: string, pageId: string = '1'): Promise<RecognitionResult> {
    return request<RecognitionResult>(`/api/v1/documents/${documentId}/pages/${pageId}/recognize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });
  },

  async deleteDocument(documentId: string): Promise<void> {
    return request<void>(`/api/v1/documents/${documentId}`, {
      method: 'DELETE',
    });
  },
};
