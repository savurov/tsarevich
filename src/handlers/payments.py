import json
import logging

from aiogram import F, Router, types
from aiogram.fsm.context import FSMContext

from config import PAYMENT_CURRENCY, PAYMENT_PLANS, PAYMENT_PROVIDER_TOKEN
from db import has_used_demo, record_successful_payment, upsert_user
from handlers.states import Survey
from logging_utils import log_event, log_exception

router = Router()
logger = logging.getLogger("teleg.payments")

PAYLOAD_PREFIX = "plan"
PAYMENT_ERROR_TEXT = "Не удалось создать счёт. Попробуйте ещё раз чуть позже."


def build_payment_keyboard(include_demo=True):
    buttons = []
    if include_demo:
        buttons.append(
            [types.InlineKeyboardButton(text="🎁 Демо — бесплатно", callback_data="demo_start")]
        )
    buttons += [
        [types.InlineKeyboardButton(text=plan["label"], callback_data=f"buy_plan:{plan_code}")]
        for plan_code, plan in PAYMENT_PLANS.items()
    ]
    return types.InlineKeyboardMarkup(inline_keyboard=buttons)


async def show_payment_screen(message: types.Message, state: FSMContext):
    await state.set_state(Survey.payment)
    include_demo = bool(message.from_user and not has_used_demo(message.from_user.id))
    await message.answer(
        "Выберите тариф для доступа:\n\n"
        "После выбора тарифа Telegram откроет встроенную форму оплаты.",
        reply_markup=build_payment_keyboard(include_demo=include_demo),
        parse_mode="Markdown",
    )


def build_invoice_payload(plan_code, telegram_user_id):
    return f"{PAYLOAD_PREFIX}:{plan_code}:{telegram_user_id}"


def parse_invoice_payload(payload):
    prefix, plan_code, telegram_user_id = payload.split(":", 2)
    if prefix != PAYLOAD_PREFIX:
        raise ValueError("Unexpected invoice payload prefix")
    return plan_code, int(telegram_user_id)


@router.callback_query(F.data.startswith("buy_plan:"), Survey.payment)
async def handle_buy_plan(callback: types.CallbackQuery):
    await callback.answer()
    if not callback.message or not callback.from_user or not callback.data:
        return

    plan_code = callback.data.split(":", 1)[1]
    plan = PAYMENT_PLANS.get(plan_code)
    if not plan:
        await callback.message.answer("Неизвестный тариф. Попробуйте выбрать его ещё раз.")
        return

    upsert_user(callback.from_user)
    payload = build_invoice_payload(plan_code, callback.from_user.id)
    log_event(logger, logging.INFO, "Invoice requested", telegram_user_id=callback.from_user.id, plan=plan_code, amount=plan["price_minor_units"])

    try:
        await callback.message.answer_invoice(
            title=plan["title"],
            description=plan["description"],
            payload=payload,
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency=PAYMENT_CURRENCY,
            prices=[types.LabeledPrice(label=plan["label"], amount=plan["price_minor_units"])],
            start_parameter=f"plan-{plan_code}",
        )
        log_event(logger, logging.INFO, "Invoice sent", telegram_user_id=callback.from_user.id, plan=plan_code, amount=plan["price_minor_units"])
    except Exception as exc:
        log_exception(logger, "Invoice send failed", exc, telegram_user_id=callback.from_user.id, plan=plan_code, amount=plan["price_minor_units"])
        await callback.message.answer(PAYMENT_ERROR_TEXT)


@router.pre_checkout_query()
async def handle_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    log_event(logger, logging.INFO, "Pre-checkout received", telegram_user_id=pre_checkout_query.from_user.id, amount=pre_checkout_query.total_amount)
    try:
        plan_code, telegram_user_id = parse_invoice_payload(pre_checkout_query.invoice_payload)
    except (TypeError, ValueError):
        log_event(logger, logging.WARNING, "Pre-checkout rejected", telegram_user_id=pre_checkout_query.from_user.id, reason="invalid_payload", amount=pre_checkout_query.total_amount)
        await pre_checkout_query.answer(
            ok=False,
            error_message="Не удалось проверить состав заказа. Попробуйте снова.",
        )
        return

    if plan_code not in PAYMENT_PLANS or telegram_user_id != pre_checkout_query.from_user.id:
        log_event(logger, logging.WARNING, "Pre-checkout rejected", telegram_user_id=pre_checkout_query.from_user.id, plan=plan_code, reason="stale_or_mismatched_invoice", amount=pre_checkout_query.total_amount)
        await pre_checkout_query.answer(
            ok=False,
            error_message="Этот счёт больше неактуален. Откройте новый тариф в чате с ботом.",
        )
        return

    log_event(logger, logging.INFO, "Pre-checkout approved", telegram_user_id=pre_checkout_query.from_user.id, plan=plan_code, amount=pre_checkout_query.total_amount)
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def handle_successful_payment(message: types.Message, state: FSMContext):
    from handlers.dialogs import show_district_menu

    if not message.successful_payment or not message.from_user:
        return

    payment = message.successful_payment

    try:
        plan_code, telegram_user_id = parse_invoice_payload(payment.invoice_payload)
    except (TypeError, ValueError):
        log_event(logger, logging.WARNING, "Payment received with invalid payload", telegram_user_id=message.from_user.id, amount=payment.total_amount, tg_charge=payment.telegram_payment_charge_id)
        await message.answer("Платёж получен, но не удалось распознать тариф. Напишите в поддержку.")
        return

    if telegram_user_id != message.from_user.id:
        log_event(logger, logging.WARNING, "Payment received for mismatched user", telegram_user_id=message.from_user.id, plan=plan_code, amount=payment.total_amount, tg_charge=payment.telegram_payment_charge_id)
        await message.answer("Платёж получен, но принадлежит другому пользователю.")
        return

    plan = PAYMENT_PLANS.get(plan_code)
    if not plan:
        log_event(logger, logging.WARNING, "Payment received for unknown plan", telegram_user_id=message.from_user.id, plan=plan_code, amount=payment.total_amount, tg_charge=payment.telegram_payment_charge_id)
        await message.answer("Платёж получен, но тариф не найден. Напишите в поддержку.")
        return

    log_event(logger, logging.INFO, "Payment received", telegram_user_id=message.from_user.id, plan=plan_code, amount=payment.total_amount, tg_charge=payment.telegram_payment_charge_id)

    raw_payload_json = json.dumps(
        message.model_dump(mode="json", exclude_none=False),
        ensure_ascii=True,
        default=str,
    )
    try:
        record_successful_payment(
            telegram_user_id=message.from_user.id,
            plan_code=plan_code,
            currency=payment.currency,
            total_amount=payment.total_amount,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
            duration_days=plan["duration_days"],
            subscription_expiration_date=payment.subscription_expiration_date,
            is_recurring=payment.is_recurring,
            is_first_recurring=payment.is_first_recurring,
            raw_payload_json=raw_payload_json,
        )
    except Exception as exc:
        log_exception(logger, "Payment save failed", exc, telegram_user_id=message.from_user.id, plan=plan_code, amount=payment.total_amount, tg_charge=payment.telegram_payment_charge_id)
        await message.answer("Оплата получена, но доступ пока не открылся автоматически. Напишите в поддержку.")
        return

    log_event(logger, logging.INFO, "Payment saved", telegram_user_id=message.from_user.id, plan=plan_code, amount=payment.total_amount, tg_charge=payment.telegram_payment_charge_id)

    await message.answer("Оплата прошла успешно. Доступ открыт.")
    await show_district_menu(message, state)
