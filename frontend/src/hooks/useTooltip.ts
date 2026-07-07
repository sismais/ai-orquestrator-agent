import { useState, useCallback, useRef } from 'react';

export interface UseTooltipOptions {
  delay?: number;
  closeDelay?: number;
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'auto';
}

export function useTooltip(options: UseTooltipOptions = {}) {
  const {
    delay = 200,
    closeDelay = 0,
    placement = 'auto'
  } = options;

  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();
  const closeTimeoutRef = useRef<ReturnType<typeof setTimeout>>();

  const show = useCallback((event?: React.MouseEvent) => {
    clearTimeout(closeTimeoutRef.current);
    clearTimeout(timeoutRef.current);

    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
      if (event) {
        const rect = (event.target as HTMLElement).getBoundingClientRect();
        setPosition({
          x: rect.left + rect.width / 2,
          y: rect.top
        });
      }
    }, delay);
  }, [delay]);

  const hide = useCallback(() => {
    clearTimeout(timeoutRef.current);
    clearTimeout(closeTimeoutRef.current);

    closeTimeoutRef.current = setTimeout(() => {
      setIsVisible(false);
    }, closeDelay);
  }, [closeDelay]);

  const toggle = useCallback(() => {
    if (isVisible) {
      hide();
    } else {
      show();
    }
  }, [isVisible, show, hide]);

  return {
    isVisible,
    position,
    placement,
    show,
    hide,
    toggle,
  };
}
