import { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { api } from '../lib/api';
import { Loader2, AlertCircle, RefreshCw, ArrowLeft } from 'lucide-react';
import { Reveal, AnimatedButton } from '../components/Animations';

export function Processing() {
  const { t, language } = useTranslation();
  const { documentId, pageId = '1' } = useParams();
  const navigate = useNavigate();
  const updateDocument = useAppStore(state => state.updateDocument);
  
  const [status, setStatus] = useState<'running' | 'error' | 'success'>('running');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const timerRef = useRef<any>(null);

  const isRu = language === 'ru';

  const runRecognition = async () => {
    if (!documentId) return;

    setStatus('running');
    setErrorMessage(null);
    setElapsedSeconds(0);

    timerRef.current = setInterval(() => {
      setElapsedSeconds(prev => prev + 1);
    }, 1000);

    try {
      updateDocument(documentId, { status: 'processing', step: 'processing' });
      
      const result = await api.recognizeDocument(documentId, pageId);
      
      clearInterval(timerRef.current);
      setStatus('success');
      
      updateDocument(documentId, {
        step: 'result',
        status: 'ready',
        updatedAt: new Date().toISOString(),
      });

      // Navigate to document result view
      navigate(`/documents/${documentId}`);
    } catch (err: any) {
      clearInterval(timerRef.current);
      setStatus('error');
      setErrorMessage(err.message || 'Ошибка распознавания');
      updateDocument(documentId, { status: 'error' });
    }
  };

  useEffect(() => {
    runRecognition();
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [documentId, pageId]);

  return (
    <Reveal className="flex flex-col items-center justify-center min-h-[60vh] gap-12">
      <div className="glass-surface p-10 md:p-14 rounded-[40px] flex flex-col items-center text-center max-w-lg w-full border border-black/5 dark:border-white/5 shadow-card">
        {status === 'running' && (
          <>
            <div className="relative mb-8">
              <div className="w-20 h-20 rounded-full border-4 border-emerald-500/20 animate-ping absolute inset-0" />
              <div className="w-20 h-20 rounded-full bg-emerald-500/10 flex items-center justify-center relative z-10">
                <Loader2 className="w-10 h-10 animate-spin text-emerald-600 dark:text-emerald-400" />
              </div>
            </div>

            <h2 className="text-2xl font-light mb-2">
              {isRu ? 'Распознавание страницы' : 'Recognizing page'}
            </h2>
            <p className="opacity-60 mb-8 text-sm leading-relaxed max-w-sm">
              {isRu
                ? 'Нейросеть анализирует изображение и извлекает текст. Обычно это занимает от 10 до 40 секунд.'
                : 'The AI model is analyzing image structure and transcribing text. Usually takes 10 to 40 seconds.'}
            </p>

            <div className="w-full bg-black/5 dark:bg-white/5 h-2 rounded-full overflow-hidden mb-4">
              <div
                className="bg-emerald-500 h-full transition-all duration-1000 ease-out"
                style={{ width: `${Math.min(95, (elapsedSeconds / 60) * 100)}%` }}
              />
            </div>

            <div className="flex justify-between w-full text-xs opacity-50 font-mono">
              <span>{elapsedSeconds}s</span>
              <span>120s max</span>
            </div>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="w-16 h-16 rounded-full bg-red-500/10 text-red-500 flex items-center justify-center mb-6">
              <AlertCircle className="w-8 h-8" />
            </div>

            <h2 className="text-2xl font-light mb-2 text-red-600 dark:text-red-400">
              {isRu ? 'Ошибка при обработке' : 'Processing Failed'}
            </h2>
            <p className="opacity-70 text-sm mb-8 leading-relaxed max-w-sm">
              {errorMessage || (isRu ? 'Не удалось завершить распознавание.' : 'Unable to complete recognition.')}
            </p>

            <div className="flex flex-col sm:flex-row gap-3 w-full">
              <AnimatedButton onClick={runRecognition} className="button-primary flex-1 inline-flex items-center justify-center gap-2">
                <RefreshCw className="w-4 h-4" />
                {isRu ? 'Повторить' : 'Retry'}
              </AnimatedButton>
              <AnimatedButton onClick={() => navigate('/dashboard')} className="button-secondary flex-1 inline-flex items-center justify-center gap-2">
                <ArrowLeft className="w-4 h-4" />
                {isRu ? 'К документам' : 'To Documents'}
              </AnimatedButton>
            </div>
          </>
        )}
      </div>
    </Reveal>
  );
}
