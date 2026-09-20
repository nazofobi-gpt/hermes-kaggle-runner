import React, { useState } from 'react';

const initialItems = [
  { id: 1, name: 'Existing item' },
];

export default function App() {
  const [items, setItems] = useState(initialItems);
  const [name, setName] = useState('');
  const [status, setStatus] = useState('idle');

  async function handleSubmit(event) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || status === 'saving') return;

    setStatus('saving');
    try {
      // Replace with the existing API call in the client app.
      const created = await Promise.resolve({ id: Date.now(), name: trimmed });
      // Functional update avoids stale closures and makes the successful
      // server response visible immediately without a page refresh.
      setItems(current => [...current, created]);
      setName('');
      setStatus('saved');
    } catch (error) {
      setStatus('error');
    }
  }

  return (
    <main>
      <h1>Items</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Name
          <input
            aria-label="Name"
            value={name}
            onChange={event => setName(event.target.value)}
          />
        </label>
        <button type="submit" disabled={!name.trim() || status === 'saving'}>
          {status === 'saving' ? 'Saving…' : 'Add item'}
        </button>
      </form>
      {status === 'error' && <p role="alert">Save failed. Please retry.</p>}
      <ul aria-label="Current items">
        {items.map(item => <li key={item.id}>{item.name}</li>)}
      </ul>
    </main>
  );
}
