import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useNavigate } from "react-router-dom";
import {
  TextField,
  Input,
  Label,
  FieldError,
  Button,
  Alert,
  Card,
} from "@heroui/react";
import { useLogin, useChangePassword, type Me } from "@/lib/admin";

const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});
type LoginForm = z.infer<typeof loginSchema>;

const pwSchema = z
  .object({
    currentPassword: z.string().min(1, "Required"),
    newPassword: z.string().min(8, "At least 8 characters"),
    confirm: z.string().min(1, "Required"),
  })
  .refine((v) => v.newPassword === v.confirm, {
    message: "Passwords do not match",
    path: ["confirm"],
  });
type PwForm = z.infer<typeof pwSchema>;

function normalizeMe(res: Me | { user: Me }): Me {
  return "user" in res ? res.user : res;
}

function BrandHeader() {
  return (
    <div className="mb-6 flex flex-col items-center gap-3 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-alpine-deep to-copper text-lg font-bold text-white">
        SG
      </span>
      <div>
        <h1 className="font-display text-xl font-semibold text-foreground">
          Svaneti with Georgie
        </h1>
        <p className="text-sm text-muted">Owner dashboard</p>
      </div>
    </div>
  );
}

function ChangePasswordStep({ onDone }: { onDone: () => void }) {
  const changePw = useChangePassword();
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PwForm>({ resolver: zodResolver(pwSchema) });

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={handleSubmit((v) =>
        changePw.mutate(
          { currentPassword: v.currentPassword, newPassword: v.newPassword },
          { onSuccess: onDone },
        ),
      )}
    >
      <Alert color="warning">
        <Alert.Indicator />
        <Alert.Content>
          <Alert.Title>Set a new password</Alert.Title>
          <Alert.Description>
            You must change your password before continuing.
          </Alert.Description>
        </Alert.Content>
      </Alert>
      <TextField isInvalid={!!errors.currentPassword} className="flex flex-col gap-1">
        <Label>Current password</Label>
        <Input type="password" autoComplete="current-password" {...register("currentPassword")} />
        <FieldError>{errors.currentPassword?.message}</FieldError>
      </TextField>
      <TextField isInvalid={!!errors.newPassword} className="flex flex-col gap-1">
        <Label>New password</Label>
        <Input type="password" autoComplete="new-password" {...register("newPassword")} />
        <FieldError>{errors.newPassword?.message}</FieldError>
      </TextField>
      <TextField isInvalid={!!errors.confirm} className="flex flex-col gap-1">
        <Label>Confirm new password</Label>
        <Input type="password" autoComplete="new-password" {...register("confirm")} />
        <FieldError>{errors.confirm?.message}</FieldError>
      </TextField>
      <Button type="submit" variant="primary" fullWidth isDisabled={changePw.isPending}>
        {changePw.isPending ? "Saving…" : "Update password"}
      </Button>
    </form>
  );
}

export function Component() {
  const login = useLogin();
  const navigate = useNavigate();
  const [mustChange, setMustChange] = useState(false);
  const [genericError, setGenericError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginForm>({ resolver: zodResolver(loginSchema) });

  const onSubmit = (values: LoginForm) => {
    setGenericError(null);
    login.mutate(values, {
      onSuccess: (res) => {
        const me = normalizeMe(res);
        if (me.forcePasswordChange) setMustChange(true);
        else navigate("/admin", { replace: true });
      },
      onError: () => setGenericError("Invalid credentials. Please try again."),
    });
  };

  return (
    <div className="grid min-h-dvh place-items-center bg-gradient-to-br from-alpine-deep/10 via-background to-glacier/10 px-4">
      <div className="w-full max-w-sm">
        <Card className="border border-border bg-surface/70 p-6 backdrop-blur">
          <Card.Content className="p-0">
            <BrandHeader />
            {mustChange ? (
              <ChangePasswordStep onDone={() => navigate("/admin", { replace: true })} />
            ) : (
              <form className="flex flex-col gap-4" onSubmit={handleSubmit(onSubmit)}>
                {genericError && (
                  <Alert color="danger">
                    <Alert.Indicator />
                    <Alert.Content>
                      <Alert.Description>{genericError}</Alert.Description>
                    </Alert.Content>
                  </Alert>
                )}
                <TextField isInvalid={!!errors.email} className="flex flex-col gap-1">
                  <Label>Email</Label>
                  <Input type="email" autoComplete="email" {...register("email")} />
                  <FieldError>{errors.email?.message}</FieldError>
                </TextField>
                <TextField isInvalid={!!errors.password} className="flex flex-col gap-1">
                  <Label>Password</Label>
                  <Input
                    type="password"
                    autoComplete="current-password"
                    {...register("password")}
                  />
                  <FieldError>{errors.password?.message}</FieldError>
                </TextField>
                <Button
                  type="submit"
                  variant="primary"
                  fullWidth
                  isDisabled={login.isPending}
                >
                  {login.isPending ? "Signing in…" : "Sign in"}
                </Button>
              </form>
            )}
          </Card.Content>
        </Card>
        <p className="mt-4 text-center text-xs text-muted">
          Authorized access only. All actions are audit-logged.
        </p>
      </div>
    </div>
  );
}
