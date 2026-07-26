import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { Loader2 } from 'lucide-react';
import { Reveal, AnimatedButton } from '../components/Animations';

export function Processing() {
  const { t } = useTranslation();
  const { documentId } = useParams();
  const navigate = useNavigate();
  const updateDocument = useAppStore(state => state.updateDocument);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setProgress(p => {
        if (p >= 100) {
          clearInterval(timer);
          return 100;
        }
        return p + 10;
      });
    }, 500);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (progress >= 100 && documentId) {
      updateDocument(documentId, { step: 'result', status: 'ready' });
      navigate(`/documents/${documentId}`);
    }
  }, [progress, documentId, updateDocument, navigate]);

  return (
    <Reveal className="flex flex-col items-center justify-center min-h-[60vh] gap-12">
       <div className="glass-surface p-12 md:p-16 rounded-[40px] flex flex-col items-center text-center max-w-lg w-full">
         <Loader2 className="w-12 h-12 animate-spin opacity-40 mb-8" />
         <h2 className="h3 mb-2">{t('processing')}</h2>
         <p className="opacity-60 mb-10">You can safely leave this page. The process will continue in the background.</p>
         
         <div className="w-full bg-black/5 dark:bg-white/5 h-2 rounded-full overflow-hidden">
           <div className="bg-primary h-full transition-all duration-300" style={{ width: `${progress}%` }} />
         </div>
         <p className="mt-4 text-sm font-medium">{progress}%</p>
         
         <AnimatedButton onClick={() => navigate('/documents')} className="button-secondary mt-10 w-full">Return to Documents</AnimatedButton>
       </div>
    </Reveal>
  );
}
