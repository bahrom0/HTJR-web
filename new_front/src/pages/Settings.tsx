import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useBlocker } from 'react-router-dom';
import { AnimatePresence, motion } from 'motion/react';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { LogOut, Trash2, User, Monitor, Wand2, Bell, HardDrive, Shield, Check, ChevronDown } from 'lucide-react';
import { Reveal, AnimatedButton } from '../components/Animations';
import { UnsavedChangesModal } from '../components/UnsavedChangesModal';

const TABS = [
  { id: 'account', icon: User, labelKey: 'navAccount' },
  { id: 'appearance', icon: Monitor, labelKey: 'navAppearance' },
  { id: 'recognition', icon: Wand2, labelKey: 'navRecognition' },
  { id: 'notifications', icon: Bell, labelKey: 'navNotifications' },
  { id: 'storage', icon: HardDrive, labelKey: 'navStorage' },
  { id: 'security', icon: Shield, labelKey: 'navSecurity' },
];

function SettingRow({ label, description, children, vertical = false }: { label: string, description?: React.ReactNode, children?: React.ReactNode, vertical?: boolean }) {
  return (
    <div className={`flex ${vertical ? 'flex-col gap-3' : 'flex-col md:flex-row md:items-center justify-between gap-4'} py-5 border-b border-black/5 dark:border-white/5 last:border-0`}>
      <div className="flex flex-col gap-1 pr-4">
        <span className="font-medium">{label}</span>
        {description && <span className="text-sm opacity-60 leading-relaxed max-w-xl">{description}</span>}
      </div>
      <div className="shrink-0">
        {children}
      </div>
    </div>
  );
}

function Toggle({ checked, onChange, disabled }: { checked: boolean, onChange: (c: boolean) => void, disabled?: boolean }) {
  return (
    <button 
      type="button" role="switch" aria-checked={checked} disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-7 w-12 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-green-500/20 ${checked ? 'bg-green-500 dark:bg-green-400' : 'bg-black/10 dark:bg-white/10'} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <span className={`pointer-events-none inline-block h-6 w-6 transform rounded-full bg-white shadow-sm transition duration-200 ease-in-out ${checked ? 'translate-x-5' : 'translate-x-0'}`} />
    </button>
  );
}

function Select({ value, onChange, options }: { value: string, onChange: (v: string) => void, options: {value: string, label: string}[] }) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const selectedOption = options.find(opt => opt.value === value);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="relative inline-block w-full sm:w-auto min-w-[120px]" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="control min-h-[44px] w-full flex items-center justify-between gap-3 pr-4 pl-4 py-2 cursor-pointer bg-transparent text-left"
      >
        <span>{selectedOption?.label || value}</span>
        <ChevronDown className={`w-4 h-4 opacity-50 transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} />
      </button>
      
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 5, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 5, scale: 0.95 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="absolute z-50 top-full mt-2 left-0 w-full min-w-max bg-white dark:bg-[#202020] rounded-2xl border border-black/10 dark:border-white/10 shadow-xl py-1.5 px-1.5"
          >
            {options.map(opt => (
              <button
                key={opt.value}
                type="button"
                className={`w-full text-left px-4 py-2.5 text-sm hover:bg-black/5 dark:hover:bg-white/5 transition-colors flex items-center justify-between rounded-xl mb-1 last:mb-0 ${
                  opt.value === value ? 'bg-black/5 dark:bg-white/10 font-medium' : ''
                }`}
                onClick={() => {
                  onChange(opt.value);
                  setIsOpen(false);
                }}
              >
                {opt.label}
                {opt.value === value && <Check className="w-4 h-4" />}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export function Settings() {
  const { t, lang } = useTranslation();
  const navigate = useNavigate();
  const { user, logout, theme, language, preferences, setTheme, setLanguage, updatePreferences, setUser } = useAppStore();

  const [activeTab, setActiveTab] = useState('account');
  const [isSaving, setIsSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');

  // Local draft states
  const [draftUser, setDraftUser] = useState({ name: user?.name || '' });
  const [draftLanguage, setDraftLanguage] = useState(language);
  const [draftPrefs, setDraftPrefs] = useState(preferences);

  const hasChanges = 
    draftUser.name !== user?.name ||
    draftLanguage !== language ||
    JSON.stringify(draftPrefs) !== JSON.stringify(preferences);

  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      hasChanges && currentLocation.pathname !== nextLocation.pathname
  );

  useEffect(() => {
    // Alert on page leave if unsaved
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasChanges) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [hasChanges]);

  const handleSave = async () => {
    setIsSaving(true);
    setSaveStatus('idle');
    // Simulate API delay
    await new Promise(r => setTimeout(r, 800));
    
    setUser({ ...user, name: draftUser.name });
    setLanguage(draftLanguage);
    updatePreferences(draftPrefs);
    
    setIsSaving(false);
    setSaveStatus('saved');
    setTimeout(() => setSaveStatus('idle'), 3000);
  };

  const handleLogout = () => {
    if (hasChanges && !window.confirm("You have unsaved changes. Leave anyway?")) return;
    
    // Reset drafts so hasChanges becomes false, preventing blocker from triggering
    setDraftUser({ name: user?.name || '' });
    setDraftLanguage(language);
    setDraftPrefs(preferences);
    
    setTimeout(() => {
      logout();
      navigate('/auth/sign-in');
    }, 0);
  };

  const handleDeleteAccount = () => {
    if (window.confirm(t('deleteAccountDesc') + "\n\nAre you sure you want to proceed?")) {
      // Reset drafts so hasChanges becomes false, preventing blocker from triggering
      setDraftUser({ name: user?.name || '' });
      setDraftLanguage(language);
      setDraftPrefs(preferences);
      
      setTimeout(() => {
        logout();
        navigate('/auth/sign-in');
      }, 0);
    }
  };

  return (
    <Reveal className="flex flex-col gap-4 md:gap-10 max-w-5xl mx-auto mt-2 md:mt-4">
      
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 md:gap-6 pb-4 md:pb-6 border-b border-black/5 dark:border-white/5">
        <div>
          <h1 className="h2">{t('settings')}</h1>
          <p className="opacity-60 mt-2 text-sm max-w-md leading-relaxed">{t('settingsDesc')}</p>
        </div>
        <div className="flex items-center gap-4 md:min-h-[54px] empty:hidden">
          {saveStatus === 'saved' && (
            <span className="text-green-600 dark:text-green-400 text-sm font-medium flex items-center gap-1">
              <Check className="w-4 h-4"/> {t('changesSaved')}
            </span>
          )}
          {hasChanges && (
            <AnimatedButton onClick={handleSave} disabled={isSaving} className="button-primary px-8">
              {isSaving ? t('saving') : t('saveChanges')}
            </AnimatedButton>
          )}
        </div>
      </div>

      {/* Main Layout */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6 md:gap-8 lg:gap-12 items-start relative">
        
        <UnsavedChangesModal 
          isOpen={blocker.state === 'blocked'}
          onStay={() => blocker.state === 'blocked' && blocker.reset()}
          onLeaveWithoutSaving={() => blocker.state === 'blocked' && blocker.proceed()}
          onSaveAndLeave={async () => {
            if (blocker.state === 'blocked') {
              await handleSave();
              blocker.proceed();
            }
          }}
        />

        {/* Mobile Tab Selector */}
        <div className="md:hidden flex flex-row items-center gap-2 bg-black/5 dark:bg-white/5 p-2 rounded-2xl w-full overflow-x-auto scrollbar-hide">
          {TABS.map(tab => {
             const Icon = tab.icon;
             const isActive = activeTab === tab.id;
             return (
               <button 
                 key={tab.id}
                 onClick={() => setActiveTab(tab.id)} 
                 className={`flex items-center justify-center flex-1 min-w-[3rem] h-12 shrink-0 rounded-[14px] transition-colors ${isActive ? 'bg-white dark:bg-[#2a2a2a] shadow-sm text-primary' : 'opacity-60 hover:opacity-100 text-secondary'}`}
                 title={t(tab.labelKey as any)}
               >
                 <Icon className="w-5 h-5" strokeWidth={isActive ? 2 : 1.5} />
               </button>
             );
          })}
        </div>

        {/* Desktop Nav */}
        <div className="hidden md:flex flex-col md:col-span-4 lg:col-span-3 gap-2 md:sticky md:top-28">
          {TABS.map(tab => {
             const Icon = tab.icon;
             const isActive = activeTab === tab.id;
             return (
               <button 
                 key={tab.id}
                 onClick={() => setActiveTab(tab.id)} 
                 className={`flex items-center gap-3 px-4 py-3.5 rounded-[20px] whitespace-nowrap transition-colors text-left ${isActive ? 'bg-black/5 dark:bg-white/10 font-medium' : 'opacity-60 hover:opacity-100 hover:bg-black/5 dark:hover:bg-white/5'}`}
               >
                 <Icon className="w-5 h-5 shrink-0" strokeWidth={isActive ? 2 : 1.5} />
                 <span className="text-sm">{t(tab.labelKey as any)}</span>
               </button>
             );
          })}
        </div>

        {/* Right Content Area */}
        <div className="md:col-span-8 lg:col-span-9 min-w-0">
           <div className="glass-surface p-6 md:p-10 rounded-[32px] flex flex-col min-h-[400px]">
             <AnimatePresence mode="wait">
               <motion.div
                 key={activeTab}
                 initial={{ opacity: 0, y: 15, filter: 'blur(4px)' }}
                 animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
                 exit={{ opacity: 0, y: -15, filter: 'blur(4px)' }}
                 transition={{ duration: 0.3, ease: [0.2, 0.8, 0.2, 1] }}
                 className="flex flex-col h-full"
               >
                 {activeTab === 'account' && (
                   <div className="flex flex-col">
                     <div className="flex items-center gap-4 md:gap-6 mb-6 md:mb-8 min-w-0">
                   <div className="w-12 h-12 md:w-16 md:h-16 rounded-full bg-black/5 dark:bg-white/10 flex items-center justify-center text-lg md:text-xl font-medium shrink-0">
                     {draftUser.name.charAt(0).toUpperCase() || 'U'}
                   </div>
                   <div className="min-w-0 flex-1">
                     <h3 className="text-lg md:text-xl font-medium truncate">{draftUser.name || 'User'}</h3>
                     <div className="flex flex-wrap items-center gap-2 mt-1 text-xs md:text-sm">
                       <span className="opacity-60 truncate max-w-[170px] sm:max-w-none">{user?.email}</span>
                       <span className={`px-2 py-0.5 rounded-full text-[10px] md:text-[11px] font-medium shrink-0 ${user?.verified ? 'bg-green-500/10 text-green-700 dark:text-green-400' : 'bg-orange-500/10 text-orange-700 dark:text-orange-400'}`}>
                         {user?.verified ? t('verified') : t('notVerified')}
                       </span>
                     </div>
                   </div>
                 </div>

                 <SettingRow label={t('displayName')} description={t('displayNameDesc')} vertical>
                   <input type="text" value={draftUser.name} onChange={e => setDraftUser({...draftUser, name: e.target.value})} className="control w-full max-w-md" />
                 </SettingRow>

                 <SettingRow label={t('emailAddress')}>
                   <div className="flex items-center gap-4 w-full md:w-auto">
                     <span className="opacity-80 text-sm">{user?.email}</span>
                     <button className="text-sm font-medium opacity-50 hover:opacity-100 transition-opacity ml-auto">{t('changeEmail')}</button>
                   </div>
                 </SettingRow>

                 <SettingRow label={t('passwordSection')} description={`${t('lastChanged')} just now`}>
                   <button className="button-secondary text-sm h-10 px-4 min-h-0">{t('changePassword')}</button>
                 </SettingRow>

                 <SettingRow label={t('accountInfo')} vertical>
                   <div className="flex flex-col gap-2 text-sm opacity-60">
                     <div className="flex gap-2"><span className="w-24">User ID:</span> <span className="font-mono">{user?.id}</span></div>
                     <div className="flex gap-2"><span className="w-24">{t('memberSince')}:</span> <span>{new Date(user?.createdAt || Date.now()).toLocaleDateString()}</span></div>
                   </div>
                 </SettingRow>
               </div>
             )}

             {activeTab === 'appearance' && (
               <div className="flex flex-col">
                 <SettingRow label={t('theme')}>
                   <div className="flex bg-black/5 dark:bg-white/5 p-1 rounded-full w-full sm:w-auto">
                     {['light', 'dark', 'system'].map(tOption => (
                       <button 
                         key={tOption}
                         onClick={() => setTheme(tOption as any)} 
                         className={`flex-1 sm:flex-none px-5 py-2 rounded-full text-sm transition-all ${theme === tOption ? 'bg-white text-black dark:bg-[#2a2a2a] dark:text-white shadow-sm' : 'opacity-60 hover:opacity-100'}`}
                       >{t(tOption as any)}</button>
                     ))}
                   </div>
                 </SettingRow>

                 <SettingRow label={t('interfaceLanguage')}>
                   <Select 
                     value={draftLanguage} 
                     onChange={(v) => setDraftLanguage(v as any)} 
                     options={[{value: 'en', label: 'English'}, {value: 'ru', label: 'Русский'}]} 
                   />
                 </SettingRow>
                 
                 <SettingRow label={t('dateFormat')}>
                   <Select 
                     value={draftPrefs.dateFormat} 
                     onChange={(v) => setDraftPrefs({...draftPrefs, dateFormat: v})} 
                     options={[
                       {value: 'DD.MM.YYYY', label: 'DD.MM.YYYY'}, 
                       {value: 'MM/DD/YYYY', label: 'MM/DD/YYYY'}, 
                       {value: 'YYYY-MM-DD', label: 'YYYY-MM-DD'}
                     ]} 
                   />
                 </SettingRow>

                 <SettingRow label={t('reducedMotion')} description={t('reducedMotionDesc')}>
                   <Toggle checked={draftPrefs.reducedMotion} onChange={c => setDraftPrefs({...draftPrefs, reducedMotion: c})} />
                 </SettingRow>
               </div>
             )}

             {activeTab === 'recognition' && (
               <div className="flex flex-col">
                 <SettingRow label={t('automaticPrep')} description={t('automaticPrepDesc')}>
                   <Toggle checked={draftPrefs.autoPrepare} onChange={c => setDraftPrefs({...draftPrefs, autoPrepare: c})} />
                 </SettingRow>
                 <SettingRow label={t('imageQualityWarnings')} description={t('imageQualityWarningsDesc')}>
                   <Toggle checked={draftPrefs.qualityWarnings} onChange={c => setDraftPrefs({...draftPrefs, qualityWarnings: c})} />
                 </SettingRow>
                 <SettingRow label={t('reviewLines')} description={t('reviewLinesDesc')}>
                   <Toggle checked={draftPrefs.reviewLines} onChange={c => setDraftPrefs({...draftPrefs, reviewLines: c})} />
                 </SettingRow>
                 <SettingRow label={t('openResult')} description={t('openResultDesc')}>
                   <Toggle checked={draftPrefs.openResult} onChange={c => setDraftPrefs({...draftPrefs, openResult: c})} />
                 </SettingRow>
                 
                 <SettingRow label={t('lowQualityBehavior')}>
                   <Select 
                     value={draftPrefs.lowQualityBehavior} 
                     onChange={(v) => setDraftPrefs({...draftPrefs, lowQualityBehavior: v as any})} 
                     options={[
                       {value: 'stop', label: t('stopAndAsk')}, 
                       {value: 'continue', label: t('allowContinue')}
                     ]} 
                   />
                 </SettingRow>
                 <SettingRow label={t('defaultExportFormat')}>
                   <Select 
                     value={draftPrefs.defaultExportFormat} 
                     onChange={(v) => setDraftPrefs({...draftPrefs, defaultExportFormat: v as any})} 
                     options={[
                       {value: 'txt', label: 'TXT'}, 
                       {value: 'docx', label: 'DOCX'},
                       {value: 'pdf', label: 'PDF'},
                       {value: 'searchable_pdf', label: t('searchablePdf')}
                     ]} 
                   />
                 </SettingRow>
               </div>
             )}

             {activeTab === 'notifications' && (
               <div className="flex flex-col">
                 <SettingRow label={t('recogCompleted')} description={t('recogCompletedDesc')}>
                   <Toggle checked={draftPrefs.notifyCompleted} onChange={c => setDraftPrefs({...draftPrefs, notifyCompleted: c})} />
                 </SettingRow>
                 <SettingRow label={t('recogFailed')} description={t('recogFailedDesc')}>
                   <Toggle checked={draftPrefs.notifyFailed} onChange={c => setDraftPrefs({...draftPrefs, notifyFailed: c})} />
                 </SettingRow>
                 
                 <SettingRow label={t('browserNotifPerm')} description={t('enableBrowserNotifs')}>
                   <button className="button-secondary text-sm h-10 px-4 min-h-0 opacity-50" disabled>Not requested</button>
                 </SettingRow>
                 <SettingRow label={t('notifBehavior')} description={t('notifyBackgroundOnly')}>
                   <Toggle checked={draftPrefs.notifyBackgroundOnly} onChange={c => setDraftPrefs({...draftPrefs, notifyBackgroundOnly: c})} />
                 </SettingRow>
               </div>
             )}

             {activeTab === 'storage' && (
               <div className="flex flex-col">
                 <SettingRow label={t('storageSummary')} vertical>
                   <div className="flex gap-8 mt-2">
                     <div className="flex flex-col">
                       <span className="text-2xl font-light">12</span>
                       <span className="text-sm opacity-60">{t('documentsCount')}</span>
                     </div>
                     <div className="flex flex-col">
                       <span className="text-2xl font-light">45</span>
                       <span className="text-sm opacity-60">{t('pagesCount')}</span>
                     </div>
                     <div className="flex flex-col">
                       <span className="text-2xl font-light">~24 MB</span>
                       <span className="text-sm opacity-60">{t('spaceUsed')}</span>
                     </div>
                   </div>
                 </SettingRow>

                 <SettingRow label={t('autosave')} description={t('autosaveDesc')}>
                   <span className="text-sm opacity-60 bg-black/5 dark:bg-white/5 px-3 py-1 rounded-full">{t('autosaveEnabled')}</span>
                 </SettingRow>
                 
                 <SettingRow label={t('originalImages')} description={t('originalImagesDesc')} />
                 
                 <SettingRow label={t('trash')} description="3 documents">
                   <button className="button-secondary text-sm h-10 px-4 min-h-0 opacity-50" disabled>{t('openTrash')}</button>
                 </SettingRow>
                 <SettingRow label={t('tempFiles')} description="~12 MB">
                   <button className="button-secondary text-sm h-10 px-4 min-h-0">{t('clearTempFiles')}</button>
                 </SettingRow>
               </div>
             )}

             {activeTab === 'security' && (
               <div className="flex flex-col h-full">
                 <SettingRow label={t('currentSession')} description="Mac OS, Chrome - Active now">
                    <div className="w-2 h-2 rounded-full bg-green-500 mr-2" />
                 </SettingRow>
                 <SettingRow label={t('otherSessions')}>
                   <button className="button-secondary text-sm h-10 px-4 min-h-0 opacity-50" disabled>{t('logoutOtherDevices')}</button>
                 </SettingRow>
                 <SettingRow label={t('downloadAccountData')}>
                   <button className="button-secondary text-sm h-10 px-4 min-h-0 opacity-50" disabled>{t('downloadMyData')}</button>
                 </SettingRow>
                 
                 <SettingRow label={t('privacy')} description={t('privacyDesc')}>
                   <div className="flex gap-4">
                     <a href="#" className="text-sm font-medium opacity-60 hover:opacity-100">{t('privacyPolicy')}</a>
                     <a href="#" className="text-sm font-medium opacity-60 hover:opacity-100">{t('termsOfService')}</a>
                   </div>
                 </SettingRow>

                 <SettingRow label={t('logout')}>
                   <button onClick={handleLogout} className="button-secondary text-sm h-10 px-6 min-h-0 flex items-center gap-2"><LogOut className="w-4 h-4"/> {t('logout')}</button>
                 </SettingRow>

                 <div className="mt-auto pt-16">
                   <div className="border border-red-500/20 bg-red-500/5 p-6 rounded-[24px] flex flex-col md:flex-row gap-6 md:items-center justify-between">
                     <div>
                       <h4 className="font-medium text-red-600 dark:text-red-400 mb-1">{t('deleteAccount')}</h4>
                       <p className="text-sm opacity-60 text-red-900/60 dark:text-red-100/60 max-w-sm">{t('deleteAccountDesc')}</p>
                     </div>
                     <AnimatedButton onClick={handleDeleteAccount} className="button-secondary shrink-0 !border-red-500/20 text-red-600 dark:text-red-400 hover:!bg-red-500/10">
                        {t('deleteAccount')}
                     </AnimatedButton>
                   </div>
                 </div>
               </div>
             )}

               </motion.div>
             </AnimatePresence>
           </div>
        </div>

      </div>
    </Reveal>
  );
}
