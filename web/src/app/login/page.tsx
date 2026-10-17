import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import LoginForm from "./login-form";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-2xl font-semibold">CaSanté</CardTitle>
          <CardDescription>
            Turn scattered medical documents into one reconciled health record.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-1 rounded-md bg-muted p-3 text-sm">
            <p>
              All data in this demo is synthetic. Don&apos;t upload real medical
              documents.
            </p>
            <p className="text-muted-foreground">
              Demo account: <code>{process.env.NEXT_PUBLIC_DEMO_EMAIL}</code> /{" "}
              <code>{process.env.NEXT_PUBLIC_DEMO_PASSWORD}</code>
            </p>
          </div>
          <LoginForm />
        </CardContent>
      </Card>
    </div>
  );
}
