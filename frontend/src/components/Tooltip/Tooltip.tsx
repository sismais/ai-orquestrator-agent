import { ReactNode, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import styles from './Tooltip.module.css';

export interface TooltipProps {
  children: ReactNode;
  content: ReactNode | string;
  placement?: 'top' | 'bottom' | 'left' | 'right' | 'auto';
  trigger?: 'hover' | 'click' | 'focus';
  delay?: number;
  offset?: number;
  className?: string;
  interactive?: boolean;
  maxWidth?: number;
}

export function Tooltip({
  children,
  content,
  placement = 'auto',
  trigger = 'hover',
  delay = 200,
  offset = 8,
  className = '',
  interactive = false,
  maxWidth = 320,
}: TooltipProps) {
  const [isVisible, setIsVisible] = useState(false);
  const [actualPlacement, setActualPlacement] = useState<'top' | 'bottom' | 'left' | 'right'>(
    placement === 'auto' ? 'top' : placement
  );
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const triggerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout>>();

  // Lógica de posicionamento automático
  const calculatePosition = () => {
    if (!triggerRef.current || !tooltipRef.current) return;

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const tooltipRect = tooltipRef.current.getBoundingClientRect();
    const viewportHeight = window.innerHeight;
    const viewportWidth = window.innerWidth;

    let finalPlacement = placement === 'auto' ? 'top' : placement;
    let top = 0;
    let left = 0;

    // Determinar melhor posicionamento se for 'auto'
    if (placement === 'auto') {
      const spaceAbove = triggerRect.top;
      const spaceBelow = viewportHeight - triggerRect.bottom;
      const spaceLeft = triggerRect.left;
      const spaceRight = viewportWidth - triggerRect.right;

      if (spaceAbove >= tooltipRect.height + offset) {
        finalPlacement = 'top';
      } else if (spaceBelow >= tooltipRect.height + offset) {
        finalPlacement = 'bottom';
      } else if (spaceRight >= tooltipRect.width + offset) {
        finalPlacement = 'right';
      } else if (spaceLeft >= tooltipRect.width + offset) {
        finalPlacement = 'left';
      } else {
        finalPlacement = 'top'; // Fallback
      }
    }

    // Calcular posição baseada no placement final
    switch (finalPlacement) {
      case 'top':
        top = triggerRect.top - tooltipRect.height - offset;
        left = triggerRect.left + (triggerRect.width - tooltipRect.width) / 2;
        break;
      case 'bottom':
        top = triggerRect.bottom + offset;
        left = triggerRect.left + (triggerRect.width - tooltipRect.width) / 2;
        break;
      case 'left':
        top = triggerRect.top + (triggerRect.height - tooltipRect.height) / 2;
        left = triggerRect.left - tooltipRect.width - offset;
        break;
      case 'right':
        top = triggerRect.top + (triggerRect.height - tooltipRect.height) / 2;
        left = triggerRect.right + offset;
        break;
    }

    // Ajustar para não sair da viewport horizontalmente
    if (left < 10) {
      left = 10;
    } else if (left + tooltipRect.width > viewportWidth - 10) {
      left = viewportWidth - tooltipRect.width - 10;
    }

    // Ajustar para não sair da viewport verticalmente
    if (top < 10) {
      top = 10;
    } else if (top + tooltipRect.height > viewportHeight - 10) {
      top = viewportHeight - tooltipRect.height - 10;
    }

    setActualPlacement(finalPlacement);
    setPosition({ top, left });
  };

  // Handlers de eventos
  const handleMouseEnter = () => {
    if (trigger !== 'hover') return;
    clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(true), delay);
  };

  const handleMouseLeave = () => {
    if (trigger !== 'hover') return;
    clearTimeout(timeoutRef.current);
    if (!interactive) {
      setIsVisible(false);
    } else {
      timeoutRef.current = setTimeout(() => setIsVisible(false), 100);
    }
  };

  const handleClick = () => {
    if (trigger !== 'click') return;
    setIsVisible(!isVisible);
  };

  const handleFocus = () => {
    if (trigger !== 'focus') return;
    setIsVisible(true);
  };

  const handleBlur = () => {
    if (trigger !== 'focus') return;
    setIsVisible(false);
  };

  useEffect(() => {
    if (isVisible) {
      calculatePosition();
      // Recalcular ao redimensionar
      const handleResize = () => calculatePosition();
      window.addEventListener('resize', handleResize);
      window.addEventListener('scroll', handleResize, true);
      return () => {
        window.removeEventListener('resize', handleResize);
        window.removeEventListener('scroll', handleResize, true);
      };
    }
  }, [isVisible]);

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return (
    <>
      <div
        ref={triggerRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onClick={handleClick}
        onFocus={handleFocus}
        onBlur={handleBlur}
        className={styles.trigger}
        tabIndex={trigger === 'focus' ? 0 : undefined}
      >
        {children}
      </div>
      {isVisible && createPortal(
        <div
          ref={tooltipRef}
          className={`${styles.tooltip} ${styles[actualPlacement]} ${className}`}
          style={{
            top: position.top,
            left: position.left,
            maxWidth,
          }}
          onMouseEnter={() => interactive && clearTimeout(timeoutRef.current)}
          onMouseLeave={() => interactive && handleMouseLeave()}
          role="tooltip"
          aria-hidden={!isVisible}
        >
          <div className={styles.content}>
            {content}
          </div>
          <div className={`${styles.arrow} ${styles[`arrow-${actualPlacement}`]}`} />
        </div>,
        document.body
      )}
    </>
  );
}
