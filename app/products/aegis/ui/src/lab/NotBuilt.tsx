/** An honest placeholder for a Lab panel or view a later phase builds: it names what is missing and when it
 *  arrives, and shows nothing that looks like data. */
export function NotBuilt({ what, phase }: { what: string; phase: number }) {
  return (
    <div className="not-built" role="note">
      {what}: arrives in Phase {phase} (plan §11)
    </div>
  );
}
