// dashboard/static/dashboard/push.js
async function sendBroadcastPush({ title, body, data = {}, userIds = null }) {
  const csrftoken = getCookie('csrftoken');

  const res = await fetch('/api/push/broadcast/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': csrftoken,
    },
    credentials: 'same-origin',
    body: JSON.stringify({
      title,
      body,
      data,
      user_ids: userIds,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
}

function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== '') {
    const cookies = document.cookie.split(';');
    for (let i = 0; i < cookies.length; i++) {
      const cookie = cookies[i].trim();
      if (cookie.substring(0, name.length + 1) === name + '=') {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}
