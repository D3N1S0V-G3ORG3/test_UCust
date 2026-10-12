/**
 * File: ai/clients/PipelineStreamClient.ts
 * Production-ready TypeScript клиент для UCust AI Gateway:
 * 1. Server-Sent Events (SSE) стриминг с поддержкой EventSource и Fetch-ReadableStream.
 * 2. Автоматическое восстановление соединения через Last-Event-ID и экспоненциальный откат.
 * 3. HTTP 429 Token Bucket Rate Limit перехватчик с разбором Retry-After заголовка.
 */

export type PipelineStage =
  | 'brand_dna'
  | 'rag_research'
  | 'content_draft'
  | 'critic_review'
  | 'visual_render'
  | 'publishing'
  | 'completed'
  | 'error';

export type PipelineEventType =
  | 'step_started'
  | 'step_progress'
  | 'step_completed'
  | 'pipeline_finished'
  | 'pipeline_error';

export interface PipelineEvent {
  event_id: string;
  event_type: PipelineEventType;
  session_id: string;
  stage: PipelineStage;
  progress_pct: number;
  message: string;
  payload: Record<string, any>;
  timestamp: string;
}

export interface StreamCallbacks {
  onProgress?: (progressPct: number, message: string, stage: PipelineStage) => void;
  onEvent?: (event: PipelineEvent) => void;
  onComplete?: (finalPayload: Record<string, any>) => void;
  onError?: (error: Error) => void;
}

export interface ClientConfig {
  baseUrl?: string;
  authToken?: string;
  tenantId?: string;
  maxRetries?: number;
}

export class PipelineStreamClient {
  private baseUrl: string;
  private authToken?: string;
  private tenantId?: string;
  private maxRetries: number;

  constructor(config: ClientConfig = {}) {
    this.baseUrl = (config.baseUrl || '').replace(/\/$/, '');
    this.authToken = config.authToken;
    this.tenantId = config.tenantId;
    this.maxRetries = config.maxRetries ?? 3;
  }

  /**
   * Вызов тяжелых API эндпоинтов генерации с авто-повтором при HTTP 429 (Rate Limit).
   */
  async requestWithRateLimit<T>(
    endpoint: string,
    options: RequestInit = {},
    attempt = 1
  ): Promise<T> {
    const url = `${this.baseUrl}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
    const headers = new Headers(options.headers || {});

    if (this.authToken && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${this.authToken}`);
    }
    if (this.tenantId && !headers.has('X-Tenant-ID')) {
      headers.set('X-Tenant-ID', this.tenantId);
    }
    if (!headers.has('Content-Type') && options.body) {
      headers.set('Content-Type', 'application/json');
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    // Обработка HTTP 429 Too Many Requests
    if (response.status === 429) {
      const retryAfterHeader = response.headers.get('Retry-After');
      const retryAfterSeconds = retryAfterHeader ? parseInt(retryAfterHeader, 10) : Math.pow(2, attempt);
      const delayMs = Math.max(1, retryAfterSeconds) * 1000;

      if (attempt <= this.maxRetries) {
        console.warn(`[PipelineClient] ⏳ Rate limit exceeded (429). Retrying in ${retryAfterSeconds}s (attempt ${attempt}/${this.maxRetries})...`);
        await new Promise((resolve) => setTimeout(resolve, delayMs));
        return this.requestWithRateLimit<T>(endpoint, options, attempt + 1);
      }

      throw new Error(`Rate limit exceeded. Gateway requested Retry-After ${retryAfterSeconds}s.`);
    }

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(`API Request failed with status ${response.status}: ${errorText}`);
    }

    return response.json() as Promise<T>;
  }

  /**
   * Подключение к Server-Sent Events (SSE) стриму сессии пайплайна.
   * Возвращает функцию отписки (abort).
   */
  subscribeToPipelineStream(sessionId: string, callbacks: StreamCallbacks): () => void {
    const controller = new AbortController();
    let lastEventId: string | null = null;
    let reconnectAttempts = 0;
    let isTerminated = false;

    const connect = async () => {
      if (isTerminated) return;

      const url = `${this.baseUrl}/api/v1/pipeline/stream/${sessionId}`;
      const headers: Record<string, string> = {
        Accept: 'text/event-stream',
      };
      if (lastEventId) {
        headers['Last-Event-ID'] = lastEventId;
      }
      if (this.authToken) {
        headers['Authorization'] = `Bearer ${this.authToken}`;
      }
      if (this.tenantId) {
        headers['X-Tenant-ID'] = this.tenantId;
      }

      try {
        const response = await fetch(url, {
          headers,
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error(`SSE stream failed with status ${response.status}`);
        }

        reconnectAttempts = 0; // Сброс счетчика при успешном соединении
        const reader = response.body?.getReader();
        if (!reader) {
          throw new Error('ReadableStream not supported by browser/runtime.');
        }

        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        while (!isTerminated) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split('\n\n');
          buffer = frames.pop() || ''; // остаток незавершенного чанка

          for (const frame of frames) {
            const trimmed = frame.trim();
            if (!trimmed || trimmed.startsWith(':')) {
              // Игнорируем keep-alive ping фреймы (: ping)
              continue;
            }

            const lines = trimmed.split('\n');
            let eventType = 'message';
            let eventData = '';
            let currentId = '';

            for (const line of lines) {
              if (line.startsWith('id:')) {
                currentId = line.substring(3).trim();
                lastEventId = currentId;
              } else if (line.startsWith('event:')) {
                eventType = line.substring(6).trim();
              } else if (line.startsWith('data:')) {
                eventData = line.substring(5).trim();
              }
            }

            if (eventData) {
              try {
                const parsedEvent: PipelineEvent = JSON.parse(eventData);
                callbacks.onEvent?.(parsedEvent);
                callbacks.onProgress?.(
                  parsedEvent.progress_pct,
                  parsedEvent.message,
                  parsedEvent.stage
                );

                if (parsedEvent.event_type === 'pipeline_finished') {
                  callbacks.onComplete?.(parsedEvent.payload);
                  isTerminated = true;
                  return;
                }

                if (parsedEvent.event_type === 'pipeline_error') {
                  const errorMsg = parsedEvent.message || 'Pipeline execution failed';
                  callbacks.onError?.(new Error(errorMsg));
                  isTerminated = true;
                  return;
                }
              } catch (parseErr) {
                console.error('[PipelineClient] Failed to parse SSE event data:', parseErr);
              }
            }
          }
        }
      } catch (err: any) {
        if (controller.signal.aborted || isTerminated) {
          return;
        }

        // Автоматическое переподключение с экспоненциальным откатом
        reconnectAttempts++;
        const backoffMs = Math.min(10000, Math.pow(2, reconnectAttempts) * 1000);
        console.warn(`[PipelineClient] Connection lost. Reconnecting in ${backoffMs}ms with Last-Event-ID='${lastEventId}'...`);
        setTimeout(connect, backoffMs);
      }
    };

    connect();

    // Функция завершения стрима и освобождения сетевых ресурсов
    return () => {
      isTerminated = true;
      controller.abort();
    };
  }
}
