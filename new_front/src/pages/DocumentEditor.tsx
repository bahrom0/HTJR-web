import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { Download, ChevronLeft, ChevronRight, Check } from 'lucide-react';
import { useState } from 'react';
import { Reveal, AnimatedButton, StaggerContainer, StaggerItem } from '../components/Animations';

export function DocumentEditor() {
  const { t } = useTranslation();
  const { documentId } = useParams();
  const navigate = useNavigate();
  const documents = useAppStore(state => state.documents);
  const doc = documents.find(d => d.id === documentId);
  
  const [lines, setLines] = useState([
    { id: 1, original: "Дар ибтидои асри", current: "Дар ибтидои асри", status: 'confirmed' },
    { id: 2, original: "бистум дар Осиёи", current: "бистум дар Осиёи", status: 'doubtful' },
    { id: 3, original: "Миёна воқеаҳои", current: "Миёна воқеаҳои", status: 'doubtful' }
  ]);

  const [selectedLineId, setSelectedLineId] = useState(2);
  const selectedLine = lines.find(l => l.id === selectedLineId) || lines[0];

  return (
    <Reveal className="flex flex-col gap-4 md:gap-8 min-h-[calc(100vh-120px)] md:h-[calc(100vh-180px)]">
      {/* Header */}
      <div className="flex justify-between items-center gap-2 pb-2 md:pb-0 border-b md:border-none border-black/5 dark:border-white/5">
        <div>
          <h1 className="text-lg md:text-2xl font-medium">{t('documentReview')}</h1>
          <p className="opacity-60 text-xs md:text-sm mt-0.5">{doc?.name || t('reviewDescription')}</p>
        </div>
        <div className="flex items-center gap-2">
           <AnimatedButton onClick={() => navigate('/documents')} className="button-secondary px-3 py-1.5 md:px-5 md:py-2 text-xs md:text-sm min-h-[38px] md:min-h-[46px]">{t('save')}</AnimatedButton>
           <AnimatedButton className="button-primary px-3 py-1.5 md:px-5 md:py-2 text-xs md:text-sm min-h-[38px] md:min-h-[46px] flex items-center gap-1.5"><Download className="w-3.5 h-3.5 md:w-4 md:h-4" /> {t('download')}</AnimatedButton>
        </div>
      </div>
      
      {/* Main Grid */}
      <div className="flex flex-col md:flex-row gap-4 md:gap-6 flex-1 min-h-0">
        {/* Document Region Image Canvas Preview */}
        <div className="flex-1 glass-surface rounded-2xl md:rounded-[32px] flex items-center justify-center p-4 md:p-6 overflow-hidden relative min-h-[220px] sm:min-h-[280px] md:min-h-0">
           <div className="w-full h-full flex flex-col items-center justify-center p-2 relative">
             <div className="w-full max-w-lg bg-[#f8f5ee] dark:bg-[#22201c] text-[#2c261e] dark:text-[#ece6da] rounded-xl shadow-md border border-black/10 dark:border-white/10 p-4 flex flex-col gap-3 relative overflow-hidden">
                <div className="flex justify-between items-center border-b border-black/10 dark:border-white/10 pb-1.5 text-[10px] opacity-60 font-mono">
                   <span>LINE {selectedLine.id} REGION PREVIEW</span>
                   <span>CROP ZOOM 2.0x</span>
                </div>
                
                <div className="py-4 px-3 bg-black/5 dark:bg-white/5 rounded-lg border border-primary/40 relative">
                   <div className="font-serif italic text-base sm:text-xl md:text-2xl tracking-wide text-primary text-center select-none">
                      "{selectedLine.original}"
                   </div>
                   <div className="absolute top-1 right-2 text-[9px] font-sans bg-primary/20 text-primary px-1.5 py-0.5 rounded">
                      ORIGINAL SCAN
                   </div>
                </div>

                <div className="flex justify-between items-center text-[10px] opacity-40 font-mono pt-1">
                   <span>CONFIDENCE: 99.2%</span>
                   <span>LINE {selectedLine.id} OF {lines.length}</span>
                </div>
             </div>
           </div>
        </div>
        
        {/* Recognized Text List */}
        <div className="w-full md:w-80 lg:w-96 flex flex-col gap-3">
          <div className="glass-surface p-4 md:p-6 rounded-2xl md:rounded-[32px] flex flex-col gap-3 md:h-full overflow-hidden">
            <h3 className="font-medium text-xs md:text-sm opacity-60 px-1">{t('recognizedText')}</h3>
            
            <StaggerContainer className="flex-1 overflow-y-auto pr-1 space-y-2 md:space-y-3 max-h-[260px] md:max-h-none">
               {lines.map((line) => (
                 <StaggerItem 
                   key={line.id} 
                   onClick={() => setSelectedLineId(line.id)}
                   className={`p-3 md:p-4 rounded-xl md:rounded-2xl cursor-pointer transition-colors border ${selectedLineId === line.id ? 'bg-primary/10 border-primary/40 shadow-sm' : 'bg-transparent border-transparent hover:bg-black/5 dark:hover:bg-white/5'}`}
                 >
                   <div className="flex justify-between items-center mb-1">
                     <span className="text-[10px] md:text-xs font-medium opacity-50">Line {line.id}</span>
                     {line.status === 'confirmed' ? (
                       <span className="text-[10px] text-green-600 dark:text-green-400 font-medium flex items-center gap-1"><Check className="w-3 h-3"/> Checked</span>
                     ) : (
                       <div className="w-2 h-2 rounded-full bg-orange-400/80" />
                     )}
                   </div>
                   <input 
                     type="text" 
                     value={line.current}
                     onChange={(e) => setLines(lines.map(l => l.id === line.id ? { ...l, current: e.target.value } : l))}
                     className="w-full bg-transparent outline-none font-medium text-sm md:text-base focus:ring-1 focus:ring-primary/40 rounded px-1 py-0.5"
                   />
                 </StaggerItem>
               ))}
            </StaggerContainer>

            <div className="flex items-center justify-between pt-3 border-t border-black/5 dark:border-white/5 gap-2">
              <AnimatedButton className="w-9 h-9 md:w-10 md:h-10 rounded-full bg-black/5 dark:bg-white/5 flex items-center justify-center shrink-0" onClick={() => setSelectedLineId(Math.max(1, selectedLineId - 1))}><ChevronLeft className="w-4 h-4"/></AnimatedButton>
              <AnimatedButton className="button-secondary flex-1 py-2 text-xs md:text-sm min-h-[36px] md:min-h-[42px] text-center justify-center" onClick={() => setLines(lines.map(l => l.id === selectedLineId ? { ...l, status: 'confirmed' } : l))}>{t('confirmLine')}</AnimatedButton>
              <AnimatedButton className="w-9 h-9 md:w-10 md:h-10 rounded-full bg-black/5 dark:bg-white/5 flex items-center justify-center shrink-0" onClick={() => setSelectedLineId(Math.min(lines.length, selectedLineId + 1))}><ChevronRight className="w-4 h-4"/></AnimatedButton>
            </div>
          </div>
        </div>
      </div>
    </Reveal>
  );
}

