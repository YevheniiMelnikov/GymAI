import { useCallback, useEffect, useRef, useState } from 'react';
import { emitGenerationFailed, parseGenerationFailure } from '../ui/generation_failure';

const POLL_INTERVAL = 2000;

export interface GenerationProgress {
    progress: number;
    isActive: boolean;
    stage?: string;
    start: (taskId: string) => void;
    reset: () => void;
}

export const useGenerationProgress = (
    storageKey: string,
    onComplete?: (data?: any) => void
): GenerationProgress => {
    const [progress, setProgress] = useState(0);
    const [isActive, setIsActive] = useState(false);
    const [taskId, setTaskId] = useState<string | null>(null);
    const [stage, setStage] = useState<string>('initializing');
    const pollTimerRef = useRef<number | null>(null);
    const failureEmittedRef = useRef(false);

    useEffect(() => {
        const savedTaskId = localStorage.getItem(`generation_task_id_${storageKey}`);
        if (savedTaskId) {
            setTaskId(savedTaskId);
            setIsActive(true);
        }
    }, [storageKey]);

    const emitFailure = useCallback((data?: any) => {
        if (failureEmittedRef.current) {
            return;
        }
        const feature = storageKey === 'diet' ? 'diets' : 'workouts';
        emitGenerationFailed(parseGenerationFailure(feature, data));
        failureEmittedRef.current = true;
    }, [storageKey]);

    const pollStatus = useCallback(async (currentTaskId: string) => {
        try {
            const response = await fetch(`/api/generation-status/?task_id=${currentTaskId}`);
            if (!response.ok) {
                setIsActive(false);
                localStorage.removeItem(`generation_task_id_${storageKey}`);
                emitFailure(null);
                return;
            }

            let data: any = null;
            try {
                data = await response.json();
            } catch {
                setIsActive(false);
                localStorage.removeItem(`generation_task_id_${storageKey}`);
                emitFailure(null);
                return;
            }
            if (data.status === 'success') {
                setProgress(100);
                setStage('completed');
                setIsActive(false);
                localStorage.removeItem(`generation_task_id_${storageKey}`);
                if (onComplete) onComplete(data);
            } else if (data.status === 'error' || data.status === 'unknown') {
                setIsActive(false);
                localStorage.removeItem(`generation_task_id_${storageKey}`);
                emitFailure(data);
            } else {
                // Ensure we don't jump back
                setProgress((prev) => Math.max(prev, data.progress || 0));
                setStage(data.stage || 'processing');
            }
        } catch (e) {
            console.error('Poll failed', e);
        }
    }, [storageKey, onComplete]);

    useEffect(() => {
        if (!isActive || !taskId) return;

        pollStatus(taskId); // Initial poll
        pollTimerRef.current = window.setInterval(() => pollStatus(taskId), POLL_INTERVAL);

        // Trickle timer: slowly increment progress for smoother UI
        const trickleTimer = window.setInterval(() => {
            setProgress((prev) => {
                if (prev >= 95) return prev;
                // Slower trickle as it gets higher
                const increment = prev < 20 ? 0.5 : prev < 50 ? 0.2 : 0.05;
                return Math.min(95, prev + increment);
            });
        }, 200);

        return () => {
            if (pollTimerRef.current) {
                clearInterval(pollTimerRef.current);
            }
            clearInterval(trickleTimer);
        };
    }, [isActive, taskId, pollStatus]);

    const start = useCallback((newTaskId: string) => {
        setTaskId(newTaskId);
        setIsActive(true);
        setProgress(0);
        setStage('queued');
        failureEmittedRef.current = false;
        localStorage.setItem(`generation_task_id_${storageKey}`, newTaskId);
    }, [storageKey]);

    const reset = useCallback(() => {
        setIsActive(false);
        setProgress(0);
        setTaskId(null);
        setStage('idle');
        failureEmittedRef.current = false;
        localStorage.removeItem(`generation_task_id_${storageKey}`);
    }, [storageKey]);

    return { progress, isActive, stage, start, reset };
};
