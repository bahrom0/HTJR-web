import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useTranslation } from '../lib/i18n';
import { Reveal, AnimatedButton } from '../components/Animations';

export function SignUp() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    navigate('/auth/verify');
  };
  
  return (
    <Reveal className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="glass-surface p-10 md:p-14 rounded-[32px] w-full max-w-md">
        <h1 className="text-3xl font-light tracking-tight mb-10">{t('createAccount')}</h1>
        <form onSubmit={handleSubmit} className="flex flex-col gap-6">
          <div className="flex flex-col gap-4">
             <input type="email" placeholder={t('email')} required value={email} onChange={e => setEmail(e.target.value)} className="control w-full" />
             <input type="password" placeholder={t('password')} required value={password} onChange={e => setPassword(e.target.value)} className="control w-full" />
          </div>
          
          <AnimatedButton type="submit" className="button-primary w-full mt-2">{t('createAccount')}</AnimatedButton>
          
          <div className="flex flex-col gap-4 mt-6 text-center">
             <Link to="/auth/sign-in" className="text-sm opacity-60 hover:opacity-100 transition-opacity">{t('signIn')}</Link>
          </div>
        </form>
      </div>
    </Reveal>
  );
}
