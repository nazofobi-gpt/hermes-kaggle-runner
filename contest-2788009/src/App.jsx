import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { normalizeNumberInput } from './numberInput.js';

const schema = z.object({
  age: z.number({ error: 'Age must be a number' }).int('Use a whole number').min(1, 'Minimum is 1').max(120, 'Maximum is 120'),
});

export default function App() {
  const [submitted, setSubmitted] = useState(null);
  const { register, handleSubmit, formState: { errors }, reset } = useForm({
    resolver: zodResolver(schema),
    defaultValues: { age: '' },
  });

  return (
    <main style={{fontFamily:'system-ui',maxWidth:560,margin:'64px auto',padding:24}}>
      <h1>React Hook Form + Zod numeric input</h1>
      <p><code>type="number"</code> still produces a string in the DOM. The registration step converts non-empty values before strict <code>z.number()</code> validation.</p>
      <form onSubmit={handleSubmit(data => setSubmitted(data))} noValidate>
        <label htmlFor="age">Age (1–120)</label>
        <input id="age" type="number" min="1" max="120" aria-invalid={Boolean(errors.age)} aria-describedby="age-error" {...register('age', { setValueAs: normalizeNumberInput })} style={{display:'block',width:'100%',boxSizing:'border-box',padding:12,margin:'8px 0',fontSize:18}} />
        <div id="age-error" role="alert" style={{minHeight:24,color:'#b00020'}}>{errors.age?.message}</div>
        <button type="submit" style={{padding:'10px 16px',marginRight:8}}>Validate</button>
        <button type="button" onClick={() => { reset({age:''}); setSubmitted(null); }} style={{padding:'10px 16px'}}>Reset</button>
      </form>
      {submitted && <pre data-testid="result" style={{marginTop:24,padding:16,background:'#f4f4f4'}}>PASS: {JSON.stringify(submitted)}</pre>}
    </main>
  );
}
