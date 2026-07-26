import React, { useState } from 'react';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { useAppStore } from '../lib/store';
import { Reveal, AnimatedButton } from '../components/Animations';

export function SignIn() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const setUser = useAppStore(state => state.setUser);
  
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setUser({ id: '1', email, name: 'User', verified: true, createdAt: new Date().toISOString() });
    const from = location.state?.from?.pathname || '/';
    navigate(from, { replace: true });
  };
  
  return (
    <Reveal className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="glass-surface p-10 md:p-14 rounded-[32px] w-full max-w-md">
        <h1 className="text-4xl font-light tracking-tight mb-10 leading-tight">Tajik HTR<br/>Studio</h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="flex flex-col gap-4">
             <input type="email" placeholder={t('email')} required value={email} onChange={e => setEmail(e.target.value)} className="control w-full" />
             <input type="password" placeholder={t('password')} required value={password} onChange={e => setPassword(e.target.value)} className="control w-full" />
          </div>
          
          <AnimatedButton type="submit" className="button-primary w-full mt-2">{t('signIn')}</AnimatedButton>
          
          <div className="flex flex-col gap-4 mt-6 text-center">
             <Link to="/auth/sign-up" className="text-sm opacity-60 hover:opacity-100 transition-opacity">{t('createAccount')}</Link>
             <Link to="/auth/recover" className="text-sm opacity-60 hover:opacity-100 transition-opacity">{t('forgotPassword')}</Link>
          </div>
        </form>
      </div>
    </Reveal>
  );
}
