import PublicPageLayout, { PublicPageMeta, SUPPORT_EMAIL } from '../components/public/PublicPageLayout'

export default function TermsPage() {
  return (
    <PublicPageLayout>
      <PublicPageMeta
        title="Terms of Service — Orbit AI Calendar"
        description="Terms governing access to and use of Orbit AI Calendar and its Google Calendar integration."
      />
      <main className="public-legal-page">
        <header>
          <span className="public-kicker"><i className="bi bi-file-earmark-text" /> Terms</span>
          <h1>Terms of Service</h1>
          <p>Effective September 1, 2026</p>
        </header>

        <article>
          <section>
            <h2>1. Agreement</h2>
            <p>By accessing or using Orbit AI Calendar (“Orbit”), you agree to these Terms of Service. If you do not agree, do not use the service.</p>
          </section>

          <section>
            <h2>2. The service</h2>
            <p>
              Orbit provides work organization, messaging, task, reminder, AI assistance, and
              Google Calendar integration features. Features may change as the service develops.
              Calendar access is optional and requires you to grant permission through Google’s
              OAuth consent flow.
            </p>
          </section>

          <section>
            <h2>3. Your account and responsibilities</h2>
            <ul>
              <li>Provide accurate account information and protect your sign-in credentials.</li>
              <li>Use only Google accounts and Calendar data you are authorized to access.</li>
              <li>Review event details before confirming an AI-assisted Calendar action.</li>
              <li>Comply with applicable laws and the rights of other people.</li>
            </ul>
            <p>You are responsible for activity performed through your account and for the content and event invitations you create.</p>
          </section>

          <section>
            <h2>4. Acceptable use</h2>
            <p>You may not misuse Orbit, attempt unauthorized access, interfere with service operation, distribute malicious content, violate privacy rights, or use the service for unlawful activity.</p>
          </section>

          <section>
            <h2>5. Google Calendar integration</h2>
            <p>
              When connected, Orbit can read and manage events in the connected Google Calendar
              within the permission you grant. Creating, editing, or deleting an event in Orbit can
              change the corresponding Google Calendar event. You can disconnect the integration
              at any time from Orbit or revoke access through your Google Account.
            </p>
          </section>

          <section>
            <h2>6. AI-assisted features</h2>
            <p>
              AI output may be incomplete or inaccurate. You must review important output and
              proposed actions. Orbit requires explicit confirmation before AI-assisted flows make
              Calendar or reminder changes, but you remain responsible for the action you approve.
            </p>
          </section>

          <section>
            <h2>7. Availability and third-party services</h2>
            <p>
              Orbit depends on services such as Google Calendar, hosting providers, and configured
              AI providers. We do not control their availability or policies. Orbit is provided on
              an “as is” and “as available” basis without a guarantee of uninterrupted operation.
            </p>
          </section>

          <section>
            <h2>8. Suspension and termination</h2>
            <p>We may restrict or terminate access when necessary to protect the service, users, or legal compliance. You may stop using Orbit and disconnect Google Calendar at any time.</p>
          </section>

          <section>
            <h2>9. Limitation of liability</h2>
            <p>To the maximum extent permitted by law, Orbit’s operators are not liable for indirect, incidental, special, consequential, or punitive damages, or for loss resulting from reliance on AI output, missed reminders, or third-party service interruptions.</p>
          </section>

          <section>
            <h2>10. Changes and contact</h2>
            <p>We may update these terms as the service changes. Continued use after an update means you accept the revised terms. Questions can be sent to <a href={`mailto:${SUPPORT_EMAIL}`}>{SUPPORT_EMAIL}</a>.</p>
          </section>
        </article>
      </main>
    </PublicPageLayout>
  )
}
