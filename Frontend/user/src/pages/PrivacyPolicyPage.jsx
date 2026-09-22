import PublicPageLayout, { PublicPageMeta, SUPPORT_EMAIL } from '../components/public/PublicPageLayout'

export default function PrivacyPolicyPage() {
  return (
    <PublicPageLayout>
      <PublicPageMeta
        title="Privacy Policy — Orbit AI Calendar"
        description="Learn how Orbit AI Calendar collects, uses, protects, and deletes account and Google Calendar data."
      />
      <main className="public-legal-page">
        <header>
          <span className="public-kicker"><i className="bi bi-shield-lock" /> Privacy</span>
          <h1>Privacy Policy</h1>
          <p>Effective September 1, 2026</p>
        </header>

        <article>
          <section>
            <h2>1. Overview</h2>
            <p>
              Orbit AI Calendar (“Orbit”, “we”, “our”) helps users organize work, reminders, and
              calendar events. This policy explains the information Orbit processes, including
              information received from Google APIs, and the choices available to you.
            </p>
          </section>

          <section>
            <h2>2. Information we process</h2>
            <h3>Orbit account information</h3>
            <p>We process information such as your name, email address, authentication data, profile settings, tasks, reminders, and content you choose to provide.</p>
            <h3>Google account and Calendar information</h3>
            <p>
              When you connect Google Calendar, Google provides OAuth access and refresh tokens.
              Orbit uses the permission you grant to read and manage events on the connected
              account’s Google Calendar. Event information can include titles, descriptions,
              start and end times, attendees, links, and event identifiers.
            </p>
            <h3>Technical information</h3>
            <p>We may process security logs, timestamps, device or browser information, and service usage information needed to operate, troubleshoot, and protect Orbit.</p>
          </section>

          <section>
            <h2>3. How Google user data is used</h2>
            <p>Orbit uses Google Calendar data only to provide user-facing features that you request or enable, including:</p>
            <ul>
              <li>displaying Google Calendar events inside Orbit;</li>
              <li>checking schedules and identifying potential conflicts;</li>
              <li>creating, updating, or deleting Calendar events at your direction;</li>
              <li>detecting changes made directly in Google Calendar so the Orbit view stays current;</li>
              <li>creating reminders or AI-assisted schedule responses when you explicitly use those features.</li>
            </ul>
            <p>
              If you ask an AI feature to analyze Calendar information, the relevant information
              may be sent to the AI service provider configured for Orbit solely to produce the
              requested response. Actions that change Calendar events require user confirmation
              in AI-assisted flows.
            </p>
            <p>
              Orbit’s use and transfer of information received from Google APIs complies with the
              <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noreferrer"> Google API Services User Data Policy</a>, including its Limited Use requirements.
            </p>
          </section>

          <section>
            <h2>4. Storage and security</h2>
            <p>
              Google OAuth access and refresh tokens are encrypted at rest. Orbit stores a sync
              cursor and limited connection metadata so it can detect Calendar changes. Calendar
              events are retrieved from Google as needed; Orbit may store user-requested or
              derived records such as reminders linked to an event, but does not create a separate
              permanent copy of your complete Calendar history.
            </p>
            <p>We use reasonable administrative and technical safeguards, but no online service can guarantee absolute security.</p>
          </section>

          <section>
            <h2>5. Sharing and disclosure</h2>
            <p>
              We do not sell Google user data or use it for advertising. Information may be
              processed by service providers that host, secure, monitor, or provide configured AI
              functionality for Orbit. They may process data only to provide those services. We
              may also disclose information when required by law or necessary to protect users and
              the service.
            </p>
          </section>

          <section>
            <h2>6. Retention, deletion, and your choices</h2>
            <ul>
              <li>You can disconnect Google Calendar from the Calendar page at any time.</li>
              <li>Disconnecting attempts to revoke Google access and deletes the stored Calendar credential and linked Calendar reminders from Orbit.</li>
              <li>You can also revoke Orbit from your Google Account’s third-party access settings.</li>
              <li>You may request deletion of your Orbit account and associated personal data by contacting us.</li>
            </ul>
            <p>We retain other account data only as long as needed to provide Orbit, meet legal obligations, resolve disputes, and maintain security.</p>
          </section>

          <section>
            <h2>7. Children</h2>
            <p>Orbit is not directed to children under 13, and we do not knowingly collect their personal information.</p>
          </section>

          <section>
            <h2>8. Changes to this policy</h2>
            <p>We may update this policy as Orbit changes. We will update the effective date and provide additional notice when required.</p>
          </section>

          <section>
            <h2>9. Contact</h2>
            <p>For privacy questions or deletion requests, contact <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>.</p>
          </section>
        </article>
      </main>
    </PublicPageLayout>
  )
}
