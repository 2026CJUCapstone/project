// WebSocket을 통한 실시간 코드 실행 출력

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

export type WSMessage = 
  | { type: 'stdout'; data: string }
  | { type: 'stderr'; data: string }
  | { type: 'exit'; code: number }
  | { type: 'error'; message: string }
  | { type: 'connected' }
  | { type: 'compilation_progress'; stage: string; percent: number };

export class CompilerWebSocket {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;

  constructor(
    private onMessage: (message: WSMessage) => void,
    private onConnect?: () => void,
    private onDisconnect?: () => void,
    private onError?: (error: Event) => void
  ) {}

  connect() {
    try {
      this.ws = new WebSocket(`${WS_URL}/ws/execute`);

      this.ws.onopen = () => {
        console.log('WebSocket connected');
        this.reconnectAttempts = 0;
        this.onConnect?.();
        this.onMessage({ type: 'connected' });
      };

      this.ws.onmessage = (event) => {
        try {
          const message: WSMessage = JSON.parse(event.data);
          this.onMessage(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };

      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.onError?.(error);
      };

      this.ws.onclose = () => {
        console.log('WebSocket disconnected');
        this.onDisconnect?.();
        this.attemptReconnect();
      };
    } catch (error) {
      console.error('Failed to create WebSocket:', error);
      this.onError?.(error as Event);
    }
  }

  private attemptReconnect() {
    if (this.reconnectAttempts < this.maxReconnectAttempts) {
      this.reconnectAttempts++;
      const delay = this.reconnectDelay * this.reconnectAttempts;
      
      console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms...`);
      
      setTimeout(() => {
        this.connect();
      }, delay);
    } else {
      console.error('Max reconnection attempts reached');
      this.onMessage({ 
        type: 'error', 
        message: '서버 연결이 끊어졌습니다. 페이지를 새로고침해주세요.' 
      });
    }
  }

  /**
   * 코드 실행 요청
   */
  executeCode(code: string, input?: string) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket is not connected');
    }

    this.ws.send(JSON.stringify({
      action: 'execute',
      code,
      input,
    }));
  }

  /**
   * 실행 중인 프로세스 중단
   */
  stop() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'stop' }));
    }
  }

  /**
   * WebSocket 연결 종료
   */
  disconnect() {
    this.reconnectAttempts = this.maxReconnectAttempts; // 재연결 방지
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * 연결 상태 확인
   */
  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }
}

/**
 * WebSocket 싱글톤 인스턴스 생성 헬퍼
 */
export function createWebSocketClient(
  onMessage: (message: WSMessage) => void,
  options?: {
    onConnect?: () => void;
    onDisconnect?: () => void;
    onError?: (error: Event) => void;
  }
): CompilerWebSocket {
  return new CompilerWebSocket(
    onMessage,
    options?.onConnect,
    options?.onDisconnect,
    options?.onError
  );
}
